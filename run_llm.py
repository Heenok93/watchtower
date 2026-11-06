#!/usr/bin/env python3
"""Run Watchtower System 1 (JEV Noul) once per unique article in the queue."""
from __future__ import annotations

import argparse
import os
from typing import Any
from uuid import uuid4

from processing.system1_classifier import (
    DEFAULT_MODEL, TAXONOMY_VERSION, PROMPT_VERSION,
    classify_with_system1, persist_system1_prediction,
)
from storage.classification_queue_repository import (
    get_pending_classification_rows, mark_queue_result, queue_status_counts,
)
from storage.database import init_database


def main(
    limit: int | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    ollama_host: str | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    """Process at most `limit` unique articles; successful rows are resumable."""
    if limit is not None and limit < 0:
        raise ValueError("System 1 limit cannot be negative.")
    if provider_name not in (None, "ollama", "systemone", "jev"):
        raise ValueError("System 1 uses the Ollama SystemOne endpoint.")

    init_database()
    model_name = model or os.getenv("WATCHTOWER_SYSTEM1_MODEL", DEFAULT_MODEL)
    endpoint = ollama_host or os.getenv("WATCHTOWER_SYSTEM1_ENDPOINT")
    run_id = str(uuid4())
    initial_rows = get_pending_classification_rows()
    rows = initial_rows if limit is None else initial_rows[:limit]
    summary: dict[str, Any] = {
        "run_id": run_id, "provider": "ollama_systemone", "model": model_name,
        "prompt_version": PROMPT_VERSION, "taxonomy_version": TAXONOMY_VERSION,
        "queue_size": len(initial_rows), "selected_count": len(rows),
        "processed": 0, "relevant": 0, "not_relevant": 0, "errors": 0,
        "audit_warnings": 0, "limited_information": 0,
        "interrupted": False, "remaining_from_initial_queue": len(initial_rows),
        "profiles": {},
    }

    print("=" * 78)
    print("WATCHTOWER — SYSTEM 1 CLASSIFICATION")
    print(f"Model: {model_name} | Articles: {len(rows)} | Run: {run_id}")
    print("One SystemOne request per unique article; eight independent Noul scores.")

    try:
        for index, row in enumerate(rows, start=1):
            article_id = int(row["article_id"])
            print(f"\n[{index}/{len(rows)}] Article {article_id}: {row['title'][:120]}")
            try:
                prediction, envelope, latency_ms = classify_with_system1(
                    article_id=article_id, title=row["title"], abstract=row["abstract"],
                    model=model_name, endpoint=endpoint, timeout=timeout,
                )
                prediction_id = persist_system1_prediction(
                    article_id=article_id, run_id=run_id, prediction=prediction,
                    envelope=envelope, elapsed_ms=latency_ms,
                    input_hash=row["input_hash"], model_name=model_name,
                )
                mark_queue_result(article_id, status="system1_done", prediction_id=prediction_id)
                summary["processed"] += 1
                if any(prediction.labels.as_dict().values()):
                    summary["relevant"] += 1
                else:
                    summary["not_relevant"] += 1
                print("    " + " | ".join(
                    f"{name}={prediction.scores.as_dict()[name]:.3f}"
                    for name in prediction.scores.as_dict()
                ) + f" | {latency_ms / 1000:.1f}s")
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                summary["errors"] += 1
                mark_queue_result(article_id, status="error", error=f"{type(exc).__name__}: {exc}")
                print(f"    ERROR: {type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        summary["interrupted"] = True
        print("\nInterrupted. Completed predictions are persisted; rerun to resume.")

    status_counts = queue_status_counts()
    summary["queue_status"] = status_counts
    summary["remaining_from_initial_queue"] = max(
        len(initial_rows) - summary["processed"] - summary["errors"], 0
    )
    print("\nSYSTEM 1 SUMMARY")
    for key in ("queue_size", "selected_count", "processed", "relevant", "not_relevant", "errors", "remaining_from_initial_queue"):
        print(f"{key:<30}{summary[key]}")
    print(f"Queue statuses: {status_counts}")
    return summary


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Maximum unique articles; default all pending.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    summary = main(limit=args.limit, model=args.model, ollama_host=args.endpoint, timeout=args.timeout)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(cli())
