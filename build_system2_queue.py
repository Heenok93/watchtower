#!/usr/bin/env python3
"""Route uncertain System 1 articles to the persistent System 2 queue."""
from __future__ import annotations

import argparse
import json
from typing import Any

from processing.system2_routing import CUTOFFS, CALIBRATION_VERSION, SCENARIO, route_scores
from storage import database


def build_queue(*, dry_run: bool = False, limit: int | None = None) -> dict[str, Any]:
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    database.init_database()
    with database.get_connection() as conn:
        rows = conn.execute(
            """SELECT q.article_id, q.status, q.input_hash, q.system1_prediction_id,
                      q.system2_prediction_id, p.scores_json, p.input_hash AS prediction_input_hash,
                      p.status AS prediction_status, a.title
               FROM classification_queue q
               JOIN articles a ON a.id = q.article_id
               LEFT JOIN model_predictions p ON p.id = q.system1_prediction_id
               WHERE q.is_eligible = 1 AND q.status IN ('system1_done', 'system2_pending')
               ORDER BY q.article_id"""
        ).fetchall()

        summary: dict[str, Any] = {
            "calibration_version": CALIBRATION_VERSION,
            "scenario": SCENARIO,
            "cutoffs": CUTOFFS,
            "eligible_system1_articles": len(rows),
            "routed_articles": 0,
            "already_routed": 0,
            "already_has_system2_prediction": 0,
            "missing_or_stale_system1_prediction": 0,
            "no_review_needed": 0,
            "review_dimension_counts": {},
            "dry_run": dry_run,
        }
        updates: list[tuple[str, str, int]] = []
        for row in rows:
            article_id = int(row["article_id"])
            if row["prediction_status"] != "completed" or not row["scores_json"] or row["prediction_input_hash"] != row["input_hash"]:
                summary["missing_or_stale_system1_prediction"] += 1
                continue
            if row["system2_prediction_id"] is not None:
                summary["already_has_system2_prediction"] += 1
                continue
            scores = json.loads(row["scores_json"])
            routing = route_scores(scores)
            if not routing["needs_system2"]:
                summary["no_review_needed"] += 1
                continue
            if row["status"] == "system2_pending":
                summary["already_routed"] += 1
            else:
                updates.append((json.dumps(routing["review_dimensions"]), CALIBRATION_VERSION, article_id))
                summary["routed_articles"] += 1
            for dimension in routing["review_dimensions"]:
                summary["review_dimension_counts"][dimension] = summary["review_dimension_counts"].get(dimension, 0) + 1

        if limit is not None:
            updates = updates[:limit]
            summary["routed_articles"] = len(updates)
        if not dry_run:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            for dimensions_json, calibration_version, article_id in updates:
                conn.execute(
                    """UPDATE classification_queue
                       SET status = 'system2_pending', system2_review_dimensions_json = ?,
                           system2_calibration_version = ?, last_error = NULL, updated_at = ?
                       WHERE article_id = ? AND is_eligible = 1 AND system2_prediction_id IS NULL""",
                    (dimensions_json, calibration_version, now, article_id),
                )
            conn.commit()
        summary["total_system2_queue_after_build"] = int(conn.execute(
            """SELECT COUNT(*) FROM classification_queue
               WHERE is_eligible = 1 AND status = 'system2_pending' AND system2_prediction_id IS NULL"""
        ).fetchone()[0])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Maximum newly routed articles")
    args = parser.parse_args()
    result = build_queue(dry_run=args.dry_run, limit=args.limit)
    print("WATCHTOWER — SYSTEM 2 QUEUE")
    for key, value in result.items():
        if key != "cutoffs":
            print(f"{key}: {value}")
    return 0 if result["missing_or_stale_system1_prediction"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
