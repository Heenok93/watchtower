"""Deterministic consolidation of System 1, routed System 2 and human decisions."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

from models.classification import CLASSIFICATION_DIMENSIONS
from processing.system2_routing import CUTOFFS, CALIBRATION_VERSION
from storage.database import get_connection

TAXONOMY_VERSION = "watchtower_v2_frozen"

def _load(value: str | None, default: Any):
    return json.loads(value) if value else default

def consolidate(*, allow_pending_system2: bool = False) -> dict[str, Any]:
    """Consolidate only validated records; unresolved System 2 rows remain queued.

    Raw model_predictions are immutable. Repeated runs are idempotent and carry
    forward any explicit human adjudications already stored in adjustments_json.
    """
    now = datetime.now(timezone.utc).isoformat()
    summary = {"eligible": 0, "consolidated": 0, "skipped_system2_pending": 0,
               "system2_articles": 0, "system2_dimension_decisions": 0,
               "human_overrides_preserved": 0, "needs_review": 0, "errors": []}
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT q.*, a.title,
                   p1.scores_json AS s1_scores, p1.status AS s1_status,
                   p1.input_hash AS s1_input_hash,
                   p2.labels_json AS s2_labels, p2.status AS s2_status,
                   p2.model_role AS s2_role, p2.input_hash AS s2_input_hash
            FROM classification_queue q
            JOIN articles a ON a.id=q.article_id
            LEFT JOIN model_predictions p1 ON p1.id=q.system1_prediction_id
            LEFT JOIN model_predictions p2 ON p2.id=q.system2_prediction_id
            WHERE q.is_eligible=1 AND q.system1_prediction_id IS NOT NULL
            ORDER BY q.article_id
        """).fetchall()
        summary["eligible"] = len(rows)
        updates = []
        for row in rows:
            aid = int(row["article_id"])
            if not row["system1_prediction_id"] or row["s1_status"] != "completed":
                summary["errors"].append(f"{aid}: missing or incomplete System 1 prediction")
                continue
            if row["s1_input_hash"] != row["input_hash"]:
                summary["errors"].append(f"{aid}: System 1 input hash mismatch")
                continue
            scores = _load(row["s1_scores"], {})
            if set(scores) != set(CLASSIFICATION_DIMENSIONS):
                summary["errors"].append(f"{aid}: System 1 score dimensions mismatch")
                continue
            try:
                scores = {d: float(scores[d]) for d in CLASSIFICATION_DIMENSIONS}
                if any(not 0 <= scores[d] <= 1 for d in CLASSIFICATION_DIMENSIONS):
                    raise ValueError("score outside [0,1]")
            except Exception as exc:
                summary["errors"].append(f"{aid}: invalid System 1 scores ({exc})")
                continue

            review_dims = _load(row["system2_review_dimensions_json"], [])
            if not isinstance(review_dims, list) or len(set(review_dims)) != len(review_dims) or not set(review_dims).issubset(CLASSIFICATION_DIMENSIONS):
                summary["errors"].append(f"{aid}: invalid System 2 review dimensions")
                continue
            labels = {d: scores[d] >= CUTOFFS[d]["high"] for d in CLASSIFICATION_DIMENSIONS}
            s2_id = row["system2_prediction_id"]
            if review_dims:
                if not s2_id:
                    if allow_pending_system2:
                        summary["skipped_system2_pending"] += 1
                        continue
                    summary["errors"].append(f"{aid}: routed dimensions but no System 2 prediction")
                    continue
                if row["s2_status"] != "completed" or row["s2_role"] != "system2":
                    summary["errors"].append(f"{aid}: System 2 prediction is not completed/system2")
                    continue
                if row["s2_input_hash"] != row["input_hash"]:
                    summary["errors"].append(f"{aid}: System 2 input hash mismatch")
                    continue
                s2_labels = _load(row["s2_labels"], {})
                if set(s2_labels) != set(CLASSIFICATION_DIMENSIONS) or any(type(s2_labels[d]) is not bool for d in CLASSIFICATION_DIMENSIONS):
                    summary["errors"].append(f"{aid}: invalid System 2 labels")
                    continue
                for d in review_dims:
                    labels[d] = s2_labels[d]
                summary["system2_articles"] += 1
                summary["system2_dimension_decisions"] += len(review_dims)

            adjustments = []
            for d in review_dims:
                base = scores[d] >= CUTOFFS[d]["high"]
                adjustments.append({
                    "dimension": d, "previous_value": bool(base),
                    "new_value": bool(labels[d]), "rule_id": "system2_review",
                    "explanation": (
                        f"System 2 V2 decision in operational review band "
                        f"[{CUTOFFS[d]['low']:.3f}, {CUTOFFS[d]['high']:.3f}); "
                        f"System 1 raw score={scores[d]:.6f}. "
                        f"Calibration={CALIBRATION_VERSION}."
                    )
                })

            # Preserve manual adjudications across subsequent consolidation runs.
            current = conn.execute(
                "SELECT revision, labels_json, adjustments_json, review_status FROM article_classifications WHERE article_id=?",
                (aid,)
            ).fetchone()
            status = "final"
            if current:
                old_adjustments = _load(current["adjustments_json"], [])
                human_events = [a for a in old_adjustments
                                if str(a.get("rule_id", "")).startswith("human_")]
                latest_by_dimension = {}
                for adj in human_events:
                    if adj.get("dimension") in labels:
                        latest_by_dimension[adj["dimension"]] = adj
                    adjustments.append(adj)
                    summary["human_overrides_preserved"] += 1
                for d, adj in latest_by_dimension.items():
                    # The pending event's new_value is the preserved provisional
                    # label, including any earlier human override.
                    labels[d] = bool(adj.get("new_value"))
                    if adj.get("rule_id") == "human_review_pending":
                        status = "needs_review"
                if any(a.get("rule_id") == "human_review_pending"
                       for a in latest_by_dimension.values()):
                    status = "needs_review"
            if status == "needs_review":
                summary["needs_review"] += 1

            updates.append((aid, scores, labels, adjustments, int(row["system1_prediction_id"]),
                            int(s2_id) if s2_id else None, status, current))
        if summary["errors"]:
            raise RuntimeError("Consolidation validation failed; no rows written:\n" + "\n".join(summary["errors"]))

        for aid, scores, labels, adjustments, s1_id, s2_id, status, current in updates:
            scores_json = json.dumps(scores, sort_keys=True, separators=(",", ":"))
            labels_json = json.dumps(labels, sort_keys=True, separators=(",", ":"))
            adjustments_json = json.dumps(adjustments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if current and current["labels_json"] == labels_json and current["adjustments_json"] == adjustments_json and current["review_status"] == status:
                # Ensure queue state is repaired without creating a duplicate history revision.
                conn.execute("UPDATE classification_queue SET status='completed', last_error=NULL, updated_at=? WHERE article_id=?", (now, aid))
                continue
            revision = int(current["revision"]) + 1 if current else 1
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
            """, (aid, scores_json, labels_json, adjustments_json, TAXONOMY_VERSION,
                  s1_id, s2_id, status, revision, now))
            conn.execute("""
                INSERT INTO article_classification_history (
                    article_id,revision,scores_json,labels_json,adjustments_json,taxonomy_version,
                    system1_prediction_id,system2_prediction_id,review_status,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (aid, revision, scores_json, labels_json, adjustments_json, TAXONOMY_VERSION,
                  s1_id, s2_id, status, now))
            conn.execute("UPDATE classification_queue SET status='completed', last_error=NULL, updated_at=? WHERE article_id=?", (now, aid))
        conn.commit()
        summary["consolidated"] = len(updates)
    return summary


def cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-pending-system2", action="store_true",
                        help="Skip articles still awaiting their required System 2 review.")
    args = parser.parse_args()
    print(json.dumps(consolidate(allow_pending_system2=args.allow_pending_system2),
                     ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(cli())
