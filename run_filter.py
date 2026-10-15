import json
from pathlib import Path

import yaml

from models.schemas import (
    Article,
    TopicProfile,
)

from processing.deterministic_filter import (
    filter_article,
)

from storage.database import get_connection

from storage.topic_result_repository import (
    count_topic_results,
    save_topic_result,
)


BASE_DIR = Path(__file__).resolve().parent
TOPICS_DIR = BASE_DIR / "config" / "topics"


PROFILE_FILES = [
    "automated_reviews.yaml",
    "agentic_epidemiology.yaml",
]


def load_profile(filename):
    profile_path = TOPICS_DIR / filename

    with open(
        profile_path,
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    return TopicProfile.model_validate(data)


def load_articles():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                title,
                abstract,
                authors,
                publication_date,
                doi,
                pmid,
                source,
                source_url,
                journal,
                collected_at
            FROM articles
            ORDER BY id
            """
        ).fetchall()

    articles = []

    for row in rows:
        authors = []

        if row["authors"]:
            try:
                authors = json.loads(
                    row["authors"]
                )
            except json.JSONDecodeError:
                authors = []

        article = Article(
            title=row["title"],
            abstract=row["abstract"],
            authors=authors,
            publication_date=row["publication_date"],
            doi=row["doi"],
            pmid=row["pmid"],
            source=row["source"],
            source_url=row["source_url"],
            journal=row["journal"],
            collected_at=row["collected_at"],
        )

        articles.append(
            (
                row["id"],
                article,
            )
        )

    return articles


def process_profile(
    articles,
    profile,
):
    counts = {
        "candidate": 0,
        "llm_review": 0,
        "reject": 0,
        "errors": 0,
    }

    for article_id, article in articles:
        try:
            result = filter_article(
                article,
                profile,
            )

            save_topic_result(
                article_id=article_id,
                result=result,
            )

            counts[result.decision] += 1

        except Exception as exc:
            counts["errors"] += 1

            print(
                f"Error filtering article "
                f"{article_id}: {exc}"
            )

    return counts


def main():
    print("=" * 80)
    print("WATCHTOWER DETERMINISTIC FILTER")
    print("=" * 80)

    articles = load_articles()

    print(f"Articles loaded: {len(articles)}")

    if not articles:
        print("No articles found in database.")
        return

    for profile_filename in PROFILE_FILES:
        profile = load_profile(
            profile_filename
        )

        print()
        print("-" * 80)
        print(f"Processing profile: {profile.name}")
        print(f"Topic ID: {profile.id}")
        print("-" * 80)

        counts = process_profile(
            articles,
            profile,
        )

        print(
            f"Candidates: "
            f"{counts['candidate']}"
        )

        print(
            f"LLM review: "
            f"{counts['llm_review']}"
        )

        print(
            f"Rejected: "
            f"{counts['reject']}"
        )

        print(
            f"Errors: "
            f"{counts['errors']}"
        )

    print()
    print("=" * 80)

    print(
        "Total persisted topic results: "
        f"{count_topic_results()}"
    )


if __name__ == "__main__":
    main()