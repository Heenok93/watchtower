import json
from datetime import datetime, timezone

from storage.database import get_connection


def save_topic_result(
    article_id,
    result,
):
    processed_at = datetime.now(
        timezone.utc
    ).isoformat()

    required_groups_satisfied = int(
        result.required_groups_satisfied
    )

    matched_include = json.dumps(
        result.matched_include,
        ensure_ascii=False,
    )

    matched_context = json.dumps(
        result.matched_context,
        ensure_ascii=False,
    )

    matched_priority = json.dumps(
        result.matched_priority,
        ensure_ascii=False,
    )

    matched_exclude = json.dumps(
        result.matched_exclude,
        ensure_ascii=False,
    )

    matched_required_groups = json.dumps(
        result.matched_required_groups,
        ensure_ascii=False,
    )

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO article_topic_results (
                article_id,
                topic_id,
                score,
                decision,
                required_groups_satisfied,
                matched_include,
                matched_context,
                matched_priority,
                matched_exclude,
                matched_required_groups,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(article_id, topic_id)
            DO UPDATE SET
                score = excluded.score,
                decision = excluded.decision,
                required_groups_satisfied =
                    excluded.required_groups_satisfied,
                matched_include =
                    excluded.matched_include,
                matched_context =
                    excluded.matched_context,
                matched_priority =
                    excluded.matched_priority,
                matched_exclude =
                    excluded.matched_exclude,
                matched_required_groups =
                    excluded.matched_required_groups,
                processed_at =
                    excluded.processed_at
            """,
            (
                article_id,
                result.topic_id,
                result.score,
                result.decision,
                required_groups_satisfied,
                matched_include,
                matched_context,
                matched_priority,
                matched_exclude,
                matched_required_groups,
                processed_at,
            ),
        )

        conn.commit()


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