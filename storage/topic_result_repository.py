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