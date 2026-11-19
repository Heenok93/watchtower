#!/usr/bin/env python3

import csv
from pathlib import Path

from storage.database import get_connection, init_database


OUTPUT = Path("outputs/rejected_articles_detailed.csv")


def main():
    init_database()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.id AS article_id,
                a.title,
                a.abstract,
                a.doi,
                a.source,
                a.source_url,

                atr.topic_id,
                atr.score,
                atr.decision,
                atr.required_groups_satisfied,

                atr.matched_include,
                atr.matched_context,
                atr.matched_priority,
                atr.matched_exclude,
                atr.matched_required_groups,

                atr.processed_at

            FROM article_topic_results atr

            INNER JOIN articles a
                ON a.id = atr.article_id

            WHERE atr.decision = 'reject'

            ORDER BY
                a.id,
                atr.topic_id
            """
        ).fetchall()

    fieldnames = [
        "article_id",
        "title",
        "abstract",
        "doi",
        "source",
        "source_url",
        "topic_id",
        "score",
        "decision",
        "required_groups_satisfied",
        "matched_include",
        "matched_context",
        "matched_priority",
        "matched_exclude",
        "matched_required_groups",
        "processed_at",
    ]

    with OUTPUT.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in rows:
            writer.writerow({
                field: row[field]
                for field in fieldnames
            })

    # Number of unique rejected articles
    article_ids = {
        row["article_id"]
        for row in rows
    }

    # Number of represented topics
    topic_ids = {
        row["topic_id"]
        for row in rows
    }

    print()
    print("Rejected articles export complete")
    print("---------------------------------")
    print(f"Unique articles:      {len(article_ids):,}")
    print(f"Article-topic rows:   {len(rows):,}")
    print(f"Topics represented:   {len(topic_ids):,}")
    print(f"Written to:           {OUTPUT}")


if __name__ == "__main__":
    main()