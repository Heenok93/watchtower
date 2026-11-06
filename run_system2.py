#!/usr/bin/env python3
"""Run LFM2.5 on articles already routed to the persistent System 2 queue."""
from __future__ import annotations

import argparse
import json
import os
from typing import Any
from uuid import uuid4

from processing.system2_classifier import (
    SYSTEM2_MODEL, classify_with_system2, persist_system2_prediction,
)
from storage.classification_queue_repository import article_input_hash
from storage import database


def get_pending_system2_rows(limit: int | None = None) -> list[dict[str, Any]]:
    sql = """SELECT q.article_id, q.input_hash, q.system1_prediction_id,
                    q.system2_review_dimensions_json, a.title, a.abstract
             FROM classification_queue q JOIN articles a ON a.id = q.article_id
             WHERE q.is_eligible = 1 AND q.status = 'system2_pending'
               AND q.system2_prediction_id IS NULL
             ORDER BY q.article_id"""
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with database.get_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _mark_system2_success(article_id: int, prediction_id: int) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        conn.execute(
            """UPDATE classification_queue SET system2_prediction_id = ?,
                   system2_completed_at = ?, system2_attempts = system2_attempts + 1,
                   system2_last_attempt_at = ?, last_error = NULL, updated_at = ?
               WHERE article_id = ? AND is_eligible = 1""",
            (prediction_id, now, now, now, article_id),
        )
        conn.commit()


def _mark_system2_error(article_id: int, error: str) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        conn.execute(
            """UPDATE classification_queue SET system2_attempts = system2_attempts + 1,
                   system2_last_attempt_at = ?, last_error = ?, updated_at = ?
               WHERE article_id = ? AND is_eligible = 1""",
            (now, error[:2000], now, article_id),
        )
        conn.commit()


def main(
    *, limit: int | None = None, model: str | None = None,
    host: str | None = None, timeout: int = 300,
) -> dict[str, Any]:
    if limit is not None and limit < 0:
        raise ValueError("System 2 limit cannot be negative")
    database.init_database()
    model_name = model or os.getenv("WATCHTOWER_SYSTEM2_MODEL", SYSTEM2_MODEL)
    rows = get_pending_system2_rows(limit)
    run_id = str(uuid4())
    summary: dict[str, Any] = {
        "run_id": run_id, "provider": "ollama", "model": model_name,
        "queue_size": len(rows), "processed": 0, "errors": 0,
        "interrupted": False, "remaining": len(rows),
    }
    print("=" * 78)
    print("WATCHTOWER — SYSTEM 2 REVIEW")
    print(f"Model: {model_name} | Articles: {len(rows)} | Run: {run_id}")
    print("One LFM2.5 request per unique article; raw categorical outputs are persisted.")
    try:
        for index, row in enumerate(rows, start=1):
            article_id = int(row["article_id"])
            print(f"\n[{index}/{len(rows)}] Article {article_id}: {(row['title'] or '')[:120]}")
            try:
                actual_hash = article_input_hash(row["title"], row["abstract"])
                if actual_hash != row["input_hash"]:
                    raise RuntimeError("Article text changed after System1; refusing stale System2 review")
                prediction, raw, latency_ms = classify_with_system2(
                    title=row["title"], abstract=row["abstract"],
                    model=model_name, host=host, timeout=timeout,
                )
                prediction_id = persist_system2_prediction(
                    article_id=article_id, run_id=run_id, prediction=prediction,
                    raw=raw, latency_ms=latency_ms, input_hash=row["input_hash"],
                    model_name=model_name,
                )
                _mark_system2_success(article_id, prediction_id)
                summary["processed"] += 1
                print(f"    saved prediction={prediction_id} | {latency_ms / 1000:.1f}s")
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                summary["errors"] += 1
                _mark_system2_error(article_id, f"{type(exc).__name__}: {exc}")
                print(f"    ERROR: {type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        summary["interrupted"] = True
        print("\nInterrupted. Successful predictions are persisted; rerun to resume.")
    summary["remaining"] = len(get_pending_system2_rows())
    print("\nSYSTEM 2 SUMMARY")
    for key, value in summary.items():
        print(f"{key:<24}{value}")
    return summary


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    result = main(limit=args.limit, model=args.model, host=args.host, timeout=args.timeout)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(cli())
