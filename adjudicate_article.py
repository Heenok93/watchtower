#!/usr/bin/env python3
"""Record one human decision using an atomic UPSERT + immutable history revision."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from models.classification import CLASSIFICATION_DIMENSIONS
from storage.database import get_connection, init_database

def adjudicate(*, article_id: int, dimension: str, decision: str,
               reason: str, reviewer: str = "human") -> int:
    if article_id < 1:
        raise ValueError("article_id must be positive")
    if dimension not in CLASSIFICATION_DIMENSIONS:
        raise ValueError(f"Unknown dimension: {dimension}")
    if decision not in {"true", "false", "needs_review"}:
        raise ValueError("decision must be true, false or needs_review")
    if not reason.strip():
        raise ValueError("A non-empty reason is required")
    init_database()
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM article_classifications WHERE article_id=?", (article_id,)
        ).fetchone()
        if row is None:
            raise ValueError(
                f"No consolidated classification for article {article_id}. "
                "Run consolidation first; raw predictions are not modified."
            )
        labels = json.loads(row["labels_json"])
        scores_json = row["scores_json"]
        adjustments = json.loads(row["adjustments_json"] or "[]")
        before = bool(labels[dimension])
        if decision in {"true", "false"}:
            after = decision == "true"
            labels[dimension] = after
            status = "final"
        else:
            after = before
            status = "needs_review"
        adjustments.append({
            "dimension": dimension,
            "previous_value": before,
            "new_value": after,
            "rule_id": "human_adjudication" if decision != "needs_review" else "human_review_pending",
            "explanation": reason.strip(),
            "reviewer": reviewer,
            "decision": decision,
            "adjudicated_at": now,
        })
        latest_human = {}
        for item in adjustments:
            if str(item.get("rule_id", "")).startswith("human_"):
                latest_human[item.get("dimension")] = item
        status = "needs_review" if any(
            item.get("rule_id") == "human_review_pending"
            for item in latest_human.values()
        ) else "final"
        labels_json = json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        adjustments_json = json.dumps(adjustments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        revision = int(row["revision"]) + 1
        # Explicit UPSERT; current row and history revision share one transaction.
        conn.execute("""
            INSERT INTO article_classifications (
                article_id,scores_json,labels_json,adjustments_json,taxonomy_version,
                system1_prediction_id,system2_prediction_id,review_status,revision,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(article_id) DO UPDATE SET
                scores_json=excluded.scores_json, labels_json=excluded.labels_json,
                adjustments_json=excluded.adjustments_json, taxonomy_version=excluded.taxonomy_version,
                system1_prediction_id=excluded.system1_prediction_id,
                system2_prediction_id=excluded.system2_prediction_id,
                review_status=excluded.review_status, revision=excluded.revision,
                updated_at=excluded.updated_at
        """, (article_id, scores_json, labels_json, adjustments_json, row["taxonomy_version"],
              row["system1_prediction_id"], row["system2_prediction_id"], status, revision, now))
        conn.execute("""
            INSERT INTO article_classification_history (
                article_id,revision,scores_json,labels_json,adjustments_json,taxonomy_version,
                system1_prediction_id,system2_prediction_id,review_status,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (article_id, revision, scores_json, labels_json, adjustments_json, row["taxonomy_version"],
              row["system1_prediction_id"], row["system2_prediction_id"], status, now))
        conn.commit()
    return revision

def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article-id", type=int, required=True)
    parser.add_argument("--dimension", choices=CLASSIFICATION_DIMENSIONS, required=True)
    parser.add_argument("--decision", choices=["true", "false", "needs_review"], required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--reviewer", default="human")
    args = parser.parse_args()
    revision = adjudicate(article_id=args.article_id, dimension=args.dimension,
                          decision=args.decision, reason=args.reason, reviewer=args.reviewer)
    print(f"Adjudication saved: article={args.article_id}, revision={revision}, status={args.decision}")
    return 0

if __name__ == "__main__":
    raise SystemExit(cli())
