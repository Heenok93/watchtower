#!/usr/bin/env python3
"""Benchmark Nimble through Ollama on five real Watchtower articles.

Usage (PowerShell or Git Bash):
  python test_nimble_5_articles.py "watchtower_articles.csv"

The script makes one /v1/systemone request per article, asking two independent
category questions. It does not write to Watchtower's SQLite database.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://localhost:11434/v1/systemone"
MODEL = "nimble"
SAMPLE_SIZE = 5
RANDOM_SEED = 42

QUESTIONS = {
    "agentic_health_ai": {
        "type": "noul",
        "instructions": (
            "Does this article substantially concern agentic or autonomous "
            "AI applied to human health, healthcare, or medicine?"
        ),
        "criteria": {
            "true": (
                "The article substantially concerns agentic or autonomous AI "
                "applied to human health, healthcare, or medicine."
            ),
            "false": (
                "The article does not substantially concern agentic or "
                "autonomous AI applied to human health, healthcare, or medicine."
            ),
        },
    },
    "digital_health_ai": {
        "type": "noul",
        "instructions": (
            "Does this article substantially concern AI applied to digital "
            "health, digital healthcare, or digital clinical workflows?"
        ),
        "criteria": {
            "true": (
                "The article substantially concerns AI applied to digital "
                "health, digital healthcare, or digital clinical workflows."
            ),
            "false": (
                "The article does not substantially concern AI applied to "
                "digital health, digital healthcare, or digital clinical workflows."
            ),
        },
    },
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    # Watchtower exports may use semicolons; Sniffer handles either comma or semicolon.
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(16384)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(f, dialect=dialect))
    if not rows:
        raise ValueError(f"No rows found in {path}")
    # Strip BOM/whitespace from column names.
    cleaned = []
    for row in rows:
        cleaned.append({(k or "").lstrip("\ufeff").strip(): (v or "").strip()
                        for k, v in row.items()})
    return cleaned


def choose_sample(rows: list[dict[str, str]], count: int) -> list[dict[str, str]]:
    valid = [r for r in rows if r.get("title") and (r.get("abstract") or r.get("title"))]
    if len(valid) < count:
        raise ValueError(f"Only {len(valid)} rows have a title; cannot sample {count}.")

    # Prefer a small mix: 3 deterministic candidates and 2 pending review articles.
    candidates = [r for r in valid if r.get("selection_status") == "deterministic_candidate"]
    pending = [r for r in valid if r.get("selection_status") == "pending_llm_review"]
    rng = random.Random(RANDOM_SEED)
    rng.shuffle(candidates)
    rng.shuffle(pending)

    selected: list[dict[str, str]] = []
    selected.extend(candidates[:min(3, count, len(candidates))])
    remaining = count - len(selected)
    selected.extend(pending[:min(remaining, len(pending))])
    remaining = count - len(selected)
    if remaining:
        used = {r.get("article_id") for r in selected}
        rest = [r for r in valid if r.get("article_id") not in used]
        rng.shuffle(rest)
        selected.extend(rest[:remaining])
    return selected[:count]


def request_nimble(endpoint: str, model: str, row: dict[str, str],
                   timeout: int) -> tuple[dict[str, Any], float]:
    title = row.get("title", "").strip()
    abstract = row.get("abstract", "").strip()
    state = f"Title: {title}\n\nAbstract: {abstract or '(No abstract available.)'}"
    payload = {
        "model": model,
        "state": state,
        "questions": QUESTIONS,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {endpoint}: {exc.reason}. "
            "Make sure Ollama is running."
        ) from exc
    elapsed = time.perf_counter() - started
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {body[:500]}") from exc
    return result, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Path to Watchtower articles CSV")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--count", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--timeout", type=int, default=600, help="Per-article timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("nimble_5_articles_results.csv"))
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"CSV not found: {args.csv_path}", file=sys.stderr)
        return 2

    try:
        rows = read_csv_rows(args.csv_path)
        sample = choose_sample(rows, args.count)
    except Exception as exc:
        print(f"Could not prepare sample: {exc}", file=sys.stderr)
        return 2

    print(f"Model: {args.model}")
    print(f"Endpoint: {args.endpoint}")
    print(f"Articles: {len(sample)} (3 candidates + up to 2 pending review when available)")
    print("Each article will be sent once with two category questions.")
    print("The first request may be slower if the model has to load into memory.\n")

    output_rows: list[dict[str, Any]] = []
    durations: list[float] = []

    for index, row in enumerate(sample, start=1):
        article_id = row.get("article_id", "").strip()
        title = row.get("title", "").strip()
        print(f"[{index}/{len(sample)}] ID {article_id}: {title[:110]}")
        try:
            response, elapsed = request_nimble(args.endpoint, args.model, row, args.timeout)
            durations.append(elapsed)
            answers = response.get("answers", {})
            record: dict[str, Any] = {
                "article_id": article_id,
                "selection_status": row.get("selection_status", ""),
                "title": title,
                "seconds": round(elapsed, 2),
                "agentic_health_ai_score": (answers.get("agentic_health_ai") or {}).get("noul"),
                "digital_health_ai_score": (answers.get("digital_health_ai") or {}).get("noul"),
                "input_tokens": (response.get("usage") or {}).get("input_tokens"),
                "error": "",
            }
            output_rows.append(record)
            print(
                f"    {elapsed:.1f}s | agentic={record['agentic_health_ai_score']} "
                f"| digital_health={record['digital_health_ai_score']} "
                f"| input_tokens={record['input_tokens']}"
            )
        except Exception as exc:
            output_rows.append({
                "article_id": article_id,
                "selection_status": row.get("selection_status", ""),
                "title": title,
                "seconds": "",
                "agentic_health_ai_score": "",
                "digital_health_ai_score": "",
                "input_tokens": "",
                "error": str(exc),
            })
            print(f"    ERROR: {exc}")

    fieldnames = [
        "article_id", "selection_status", "title", "seconds",
        "agentic_health_ai_score", "digital_health_ai_score", "input_tokens", "error",
    ]
    try:
        with args.output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows)
    except OSError as exc:
        print(f"Could not write output CSV: {exc}", file=sys.stderr)
        return 2

    print(f"\nResults saved to: {args.output.resolve()}")
    if durations:
        total = sum(durations)
        print(f"Successful requests: {len(durations)}/{len(sample)}")
        print(f"Total inference time: {total:.1f}s ({total / 60:.1f} min)")
        print(f"Mean per article: {total / len(durations):.1f}s")
        print(f"Estimated 272 articles at this mean: {total / len(durations) * 272 / 3600:.2f} hours")
    return 0 if len(durations) == len(sample) else 1


if __name__ == "__main__":
    raise SystemExit(main())
