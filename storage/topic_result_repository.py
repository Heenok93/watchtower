"""Persistence helpers for deterministic topic-filter results."""
import json
from datetime import datetime, timezone

from storage.database import get_connection


def get_topic_result_metadata(topic_ids=None):
    """Return current deterministic result fingerprints keyed by (article_id, topic_id)."""
    params = ()
    where = ""
    if topic_ids:
        placeholders = ",".join("?" for _ in topic_ids)
        where = f" WHERE topic_id IN ({placeholders})"
        params = tuple(topic_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT article_id, topic_id, decision, score, profile_hash,
                       profile_version, filter_engine_version, input_hash
                FROM article_topic_results{where}""", params
        ).fetchall()
    return {(int(row["article_id"]), row["topic_id"]): dict(row) for row in rows}


def _archive_and_invalidate_legacy_llm(conn, article_id, topic_id, reason, processed_at):
    previous = conn.execute(
        """SELECT llm_decision, llm_confidence, llm_reason, llm_summary,
                  llm_provider, llm_model, llm_processed_at
           FROM article_topic_results WHERE article_id = ? AND topic_id = ?""",
        (article_id, topic_id),
    ).fetchone()
    if previous is None:
        return
    if previous["llm_processed_at"] is not None or previous["llm_decision"] is not None:
        conn.execute(
            """INSERT INTO article_topic_llm_history (
                   article_id, topic_id, llm_decision, llm_confidence, llm_reason,
                   llm_summary, llm_provider, llm_model, llm_processed_at,
                   invalidation_reason, archived_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                article_id, topic_id, previous["llm_decision"], previous["llm_confidence"],
                previous["llm_reason"], previous["llm_summary"], previous["llm_provider"],
                previous["llm_model"], previous["llm_processed_at"], reason, processed_at,
            ),
        )
    conn.execute(
        """UPDATE article_topic_results
           SET llm_decision = NULL, llm_confidence = NULL, llm_reason = NULL,
               llm_summary = NULL, llm_provider = NULL, llm_model = NULL,
               llm_processed_at = NULL
           WHERE article_id = ? AND topic_id = ?""",
        (article_id, topic_id),
    )


def save_topic_results_batch(records):
    """Persist one profile's changed results in a single transaction."""
    if not records:
        return 0
    processed_at = datetime.now(timezone.utc).isoformat()
    saved = 0
    with get_connection() as conn:
        for record in records:
            article_id = record["article_id"]
            result = record["result"]
            profile_hash = record["profile_hash"]
            profile_version = record["profile_version"]
            filter_engine_version = record["filter_engine_version"]
            input_hash = record["input_hash"]
            previous = conn.execute(
                """SELECT profile_hash, input_hash, filter_engine_version
                   FROM article_topic_results WHERE article_id = ? AND topic_id = ?""",
                (article_id, result.topic_id),
            ).fetchone()
            if previous is not None:
                changes = []
                if previous["profile_hash"] != profile_hash:
                    changes.append("profile_changed")
                if previous["input_hash"] != input_hash:
                    changes.append("article_text_changed")
                if previous["filter_engine_version"] != filter_engine_version:
                    changes.append("filter_engine_changed")
                if changes:
                    _archive_and_invalidate_legacy_llm(
                        conn, article_id, result.topic_id, "+".join(changes), processed_at
                    )
                    conn.execute(
                        """UPDATE article_classifications
                           SET review_status = 'stale', updated_at = ?
                           WHERE article_id = ?""",
                        (processed_at, article_id),
                    )
            conn.execute(
                """INSERT INTO article_topic_results (
                       article_id, topic_id, score, decision, required_groups_satisfied,
                       matched_include, matched_context, matched_priority, matched_exclude,
                       matched_required_groups, processed_at, profile_hash, profile_version,
                       filter_engine_version, input_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(article_id, topic_id) DO UPDATE SET
                       score=excluded.score, decision=excluded.decision,
                       required_groups_satisfied=excluded.required_groups_satisfied,
                       matched_include=excluded.matched_include,
                       matched_context=excluded.matched_context,
                       matched_priority=excluded.matched_priority,
                       matched_exclude=excluded.matched_exclude,
                       matched_required_groups=excluded.matched_required_groups,
                       processed_at=excluded.processed_at,
                       profile_hash=excluded.profile_hash,
                       profile_version=excluded.profile_version,
                       filter_engine_version=excluded.filter_engine_version,
                       input_hash=excluded.input_hash""",
                (
                    article_id, result.topic_id, result.score, result.decision,
                    int(result.required_groups_satisfied),
                    json.dumps(result.matched_include, ensure_ascii=False),
                    json.dumps(result.matched_context, ensure_ascii=False),
                    json.dumps(result.matched_priority, ensure_ascii=False),
                    json.dumps(result.matched_exclude, ensure_ascii=False),
                    json.dumps(result.matched_required_groups, ensure_ascii=False),
                    processed_at, profile_hash, profile_version, filter_engine_version, input_hash,
                ),
            )
            saved += 1
        conn.commit()
    return saved


def save_topic_result(article_id, result, *, profile_hash=None, profile_version=None,
                      filter_engine_version=None, input_hash=None):
    """Backward-compatible single-result wrapper."""
    return save_topic_results_batch([{
        "article_id": article_id, "result": result, "profile_hash": profile_hash,
        "profile_version": profile_version, "filter_engine_version": filter_engine_version,
        "input_hash": input_hash,
    }])


def save_llm_result(
    article_id,
    topic_id,
    result,
    provider_name,
    model_name,
):
    """
    Persist an LLM classification for an existing
    article/topic result.

    The deterministic decision is intentionally
    left unchanged.
    """

    llm_processed_at = datetime.now(
        timezone.utc
    ).isoformat()

    llm_decision = (
        "relevant"
        if result.relevant
        else "not_relevant"
    )

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE article_topic_results
            SET
                llm_decision = ?,
                llm_confidence = ?,
                llm_reason = ?,
                llm_summary = ?,
                llm_provider = ?,
                llm_model = ?,
                llm_processed_at = ?
            WHERE article_id = ?
              AND topic_id = ?
              AND decision = 'llm_review'
            """,
            (
                llm_decision,
                result.confidence,
                result.reason,
                result.summary,
                provider_name,
                model_name,
                llm_processed_at,
                article_id,
                topic_id,
            ),
        )

        conn.commit()

        return cursor.rowcount


def count_topic_results():
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM article_topic_results
            """
        ).fetchone()

    return row["count"]


def get_topic_result_counts():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                topic_id,
                decision,
                COUNT(*) AS count
            FROM article_topic_results
            GROUP BY topic_id, decision
            ORDER BY topic_id, decision
            """
        ).fetchall()

    return rows


def get_llm_review_results(
    only_unprocessed=True,
):
    """
    Return article/topic pairs requiring LLM review.

    By default, only rows that have not already been
    classified by an LLM are returned.
    """

    where_clause = """
        article_topic_results.decision = 'llm_review'
    """

    if only_unprocessed:
        where_clause += """
        AND article_topic_results.llm_processed_at IS NULL
        """

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                article_topic_results.id,
                article_topic_results.article_id,
                article_topic_results.topic_id,
                article_topic_results.score,
                article_topic_results.decision,
                article_topic_results.required_groups_satisfied,
                article_topic_results.matched_include,
                article_topic_results.matched_context,
                article_topic_results.matched_priority,
                article_topic_results.matched_exclude,
                article_topic_results.matched_required_groups,
                article_topic_results.processed_at,

                article_topic_results.llm_decision,
                article_topic_results.llm_confidence,
                article_topic_results.llm_reason,
                article_topic_results.llm_summary,
                article_topic_results.llm_provider,
                article_topic_results.llm_model,
                article_topic_results.llm_processed_at,

                articles.title,
                articles.abstract,
                articles.authors,
                articles.publication_date,
                articles.doi,
                articles.pmid,
                articles.source,
                articles.source_url,
                articles.journal,
                articles.content_type

            FROM article_topic_results

            INNER JOIN articles
                ON articles.id =
                   article_topic_results.article_id

            WHERE {where_clause}

            ORDER BY
                article_topic_results.topic_id,
                article_topic_results.score DESC,
                articles.title
            """
        ).fetchall()

    return rows


def get_reviewable_topic_results():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                article_topic_results.id,
                article_topic_results.article_id,
                article_topic_results.topic_id,
                article_topic_results.score,
                article_topic_results.decision,
                article_topic_results.required_groups_satisfied,
                article_topic_results.matched_include,
                article_topic_results.matched_context,
                article_topic_results.matched_priority,
                article_topic_results.matched_exclude,
                article_topic_results.matched_required_groups,
                article_topic_results.processed_at,

                article_topic_results.llm_decision,
                article_topic_results.llm_confidence,
                article_topic_results.llm_reason,
                article_topic_results.llm_summary,
                article_topic_results.llm_provider,
                article_topic_results.llm_model,
                article_topic_results.llm_processed_at,

                articles.title,
                articles.doi,
                articles.source,
                articles.source_url

            FROM article_topic_results

            INNER JOIN articles
                ON articles.id =
                   article_topic_results.article_id

            WHERE article_topic_results.decision IN (
                'candidate',
                'llm_review'
            )

            ORDER BY
                article_topic_results.topic_id,
                article_topic_results.score DESC,
                articles.title
            """
        ).fetchall()

    return rows