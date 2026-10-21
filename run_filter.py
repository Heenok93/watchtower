import json
from contextlib import closing
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


def discover_profile_files():
    """
    Discover all YAML topic profiles.

    Adding a new .yaml file to config/topics is enough
    to make it available to the deterministic filter.
    """
    if not TOPICS_DIR.exists():
        raise FileNotFoundError(
            f"Topics directory not found: {TOPICS_DIR}"
        )

    profile_files = sorted(
        path.name
        for path in TOPICS_DIR.glob("*.yaml")
        if path.is_file()
    )

    if not profile_files:
        raise RuntimeError(
            f"No topic profiles found in {TOPICS_DIR}"
        )

    return profile_files


def load_profile(filename):
    """
    Load and validate one scientific topic profile.
    """
    profile_path = TOPICS_DIR / filename

    with open(
        profile_path,
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    if not data:
        raise ValueError(
            f"Empty topic profile: {profile_path}"
        )

    profile = TopicProfile.model_validate(
        data
    )

    return profile


def load_articles():
    """
    Load all collected articles from the database.
    """
    with closing(
        get_connection()
    ) as conn:
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
    """
    Apply the deterministic filter to all articles
    for one topic profile.
    """
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

            if result.decision not in counts:
                raise ValueError(
                    "Unexpected filter decision: "
                    f"{result.decision}"
                )

            counts[result.decision] += 1

        except Exception as exc:
            counts["errors"] += 1

            print(
                f"Error filtering article "
                f"{article_id}: "
                f"{type(exc).__name__}: {exc}"
            )

    return counts


def main():
    print("=" * 80)
    print("WATCHTOWER DETERMINISTIC FILTER")
    print("=" * 80)

    profile_files = discover_profile_files()

    print(
        f"Topic profiles discovered: "
        f"{len(profile_files)}"
    )

    for filename in profile_files:
        print(f"  - {filename}")

    articles = load_articles()

    print()
    print(
        f"Articles loaded: "
        f"{len(articles)}"
    )

    if not articles:
        print("No articles found in database.")
        return

    total_errors = 0

    for profile_filename in profile_files:
        print()
        print("-" * 80)

        try:
            profile = load_profile(
                profile_filename
            )

        except Exception as exc:
            total_errors += 1

            print(
                f"PROFILE ERROR: "
                f"{profile_filename}"
            )

            print(
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            continue

        print(
            f"Processing profile: "
            f"{profile.name}"
        )

        print(
            f"Topic ID: "
            f"{profile.id}"
        )

        print("-" * 80)

        counts = process_profile(
            articles,
            profile,
        )

        total_errors += counts[
            "errors"
        ]

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

    print(
        f"Total errors: "
        f"{total_errors}"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()