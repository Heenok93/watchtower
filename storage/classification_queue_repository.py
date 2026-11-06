"""Persistent, idempotent article-level classification queue."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from storage.database import get_connection


def article_input_hash(title: str | None, abstract: str | None) -> str:
    payload = json.dumps(
        {"title": title or "", "abstract": abstract or ""},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_classification_queue(
    *, taxonomy_version: str, prompt_version: str,
    topic_ids: list[str] | None = None,
) -> dict[str, int]:
    """Upsert one queue row per article in the current llm_review union.

    Completed rows are reused only when article text, taxonomy and prompt versions
    are unchanged. Topic provenance is refreshed independently of model execution.
    """
    now = datetime.now(timezone.utc).isoformat()
    params: list[Any] = []
    topic_filter = ""
    if topic_ids:
        placeholders = ",".join("?" for _ in topic_ids)
        topic_filter = f" AND r.topic_id IN ({placeholders})"
        params.extend(topic_ids)

    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT a.id AS article_id, a.title, a.abstract, r.topic_id
                FROM article_topic_results r
                JOIN articles a ON a.id = r.article_id
                WHERE r.decision = 'llm_review' {topic_filter}
                ORDER BY a.id, r.topic_id""",
            params,
        ).fetchall()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            aid = int(row["article_id"])
            item = grouped.setdefault(aid, {
                "title": row["title"] or "", "abstract": row["abstract"] or "",
                "topics": set(),
            })
            item["topics"].add(str(row["topic_id"]))

        conn.execute("UPDATE classification_queue SET is_eligible = 0, updated_at = ? WHERE is_eligible = 1", (now,))
        counts = {"eligible_articles": len(grouped), "inserted": 0, "updated": 0,
                  "reused": 0, "reactivated": 0}
        for aid, item in grouped.items():
            digest = article_input_hash(item["title"], item["abstract"])
            topics_json = json.dumps(sorted(item["topics"]), ensure_ascii=False)
            previous = conn.execute(
                "SELECT * FROM classification_queue WHERE article_id = ?", (aid,)
            ).fetchone()
            if previous is None:
                conn.execute(
                    """INSERT INTO classification_queue (
                        article_id, review_topic_ids_json, status, is_eligible,
                        input_hash, taxonomy_version, system1_prompt_version,
                        created_at, updated_at
                    ) VALUES (?, ?, 'pending', 1, ?, ?, ?, ?, ?)""",
                    (aid, topics_json, digest, taxonomy_version, prompt_version, now, now),
                )
                counts["inserted"] += 1
                continue

            changed = (
                previous["input_hash"] != digest
                or previous["taxonomy_version"] != taxonomy_version
                or previous["system1_prompt_version"] != prompt_version
            )
            reactivated = not bool(previous["is_eligible"])
            if changed:
                # A changed article input, taxonomy or System 1 prompt invalidates
                # the current consolidated result without deleting its history.
                current = conn.execute(
                    "SELECT * FROM article_classifications WHERE article_id = ?", (aid,)
                ).fetchone()
                if current is not None and current["review_status"] != "stale":
                    stale_revision = int(current["revision"]) + 1
                    conn.execute(
                        """UPDATE article_classifications SET review_status='stale',
                               revision=?, updated_at=? WHERE article_id=?""",
                        (stale_revision, now, aid),
                    )
                    conn.execute(
                        """INSERT INTO article_classification_history (
                            article_id,revision,scores_json,labels_json,adjustments_json,
                            taxonomy_version,system1_prediction_id,system2_prediction_id,
                            review_status,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (aid, stale_revision, current["scores_json"], current["labels_json"],
                         current["adjustments_json"], current["taxonomy_version"],
                         current["system1_prediction_id"], current["system2_prediction_id"],
                         "stale", now),
                    )
                conn.execute(
                    """UPDATE classification_queue SET
                        review_topic_ids_json = ?, status = 'pending', is_eligible = 1,
                        input_hash = ?, taxonomy_version = ?, system1_prompt_version = ?,
                        system1_prediction_id = NULL, system2_prediction_id = NULL,
                        system2_review_dimensions_json = '[]',
                        system2_calibration_version = NULL,
                        system2_attempts = 0, system2_last_attempt_at = NULL,
                        system2_completed_at = NULL,
                        last_error = NULL, updated_at = ?
                       WHERE article_id = ?""",
                    (topics_json, digest, taxonomy_version, prompt_version, now, aid),
                )
                counts["updated"] += 1
            else:
                conn.execute(
                    """UPDATE classification_queue SET review_topic_ids_json = ?,
                        is_eligible = 1, status = CASE WHEN status = 'obsolete' THEN 'pending' ELSE status END,
                        updated_at = ? WHERE article_id = ?""",
                    (topics_json, now, aid),
                )
                counts["reused"] += 1
                if reactivated:
                    counts["reactivated"] += 1
        # Mark rows that disappeared from the current union as obsolete without
        # deleting their predictions or audit history.
        conn.execute(
            """UPDATE classification_queue SET status = 'obsolete', updated_at = ?
               WHERE is_eligible = 0 AND status IN ('pending', 'error')""", (now,)
        )
        conn.commit()
    return counts


def get_pending_classification_rows(limit: int | None = None) -> list[dict[str, Any]]:
    sql = """SELECT q.*, a.title, a.abstract, a.doi, a.pmid, a.source,
                    a.source_url, a.journal, a.content_type
             FROM classification_queue q JOIN articles a ON a.id = q.article_id
             WHERE q.is_eligible = 1 AND q.status IN ('pending', 'error')
             ORDER BY q.article_id"""
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def mark_queue_result(article_id: int, *, status: str, prediction_id: int | None = None,
                      error: str | None = None) -> None:
    if status not in {"system1_done", "system2_pending", "completed", "error"}:
        raise ValueError(f"Unsupported queue status: {status}")
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE classification_queue SET status = ?,
                system1_prediction_id = CASE WHEN ? IS NULL THEN system1_prediction_id ELSE ? END,
                last_error = ?, updated_at = ? WHERE article_id = ?""",
            (status, prediction_id, prediction_id, error, now, article_id),
        )
        conn.commit()


def queue_status_counts() -> dict[str, int]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM classification_queue WHERE is_eligible = 1 GROUP BY status"
        ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}
