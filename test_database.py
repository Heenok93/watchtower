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


BASE_DIR = Path(__file__).resolve().parent
TOPICS_DIR = BASE_DIR / "config" / "topics"


def load_profile(filename):
    profile_path = TOPICS_DIR / filename

    with open(
        profile_path,
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    return TopicProfile.model_validate(data)


def load_nature_articles():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
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
            WHERE source = ?
            ORDER BY id
            """,
            ("nature",),
        ).fetchall()

    articles = []

    for row in rows:
        authors = []

        if row["authors"]:
            try:
                authors = json.loads(row["authors"])
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

        articles.append(article)

    return articles


def evaluate_profile(
    articles,
    profile,
):
    results = []

    counts = {
        "candidate": 0,
        "llm_review": 0,
        "reject": 0,
    }

    for article in articles:
        result = filter_article(
            article,
            profile,
        )

        counts[result.decision] += 1
        results.append((article, result))

    return counts, results


def print_results(
    profile,
    counts,
    results,
):
    print()
    print("=" * 80)
    print(f"PROFILE: {profile.name}")
    print("=" * 80)

    print(f"Total articles: {sum(counts.values())}")
    print(f"Candidates: {counts['candidate']}")
    print(f"LLM review: {counts['llm_review']}")
    print(f"Rejected: {counts['reject']}")

    interesting = [
        (article, result)
        for article, result in results
        if result.decision != "reject"
    ]

    interesting.sort(
        key=lambda item: item[1].score,
        reverse=True,
    )

    print()
    print("ARTICLES TO REVIEW")
    print("-" * 80)

    if not interesting:
        print("None")
        return

    for article, result in interesting:
        print()
        print(f"TITLE: {article.title}")
        print(f"DECISION: {result.decision}")
        print(f"SCORE: {result.score}")

        print(
            "REQUIRED GROUPS OK: "
            f"{result.required_groups_satisfied}"
        )

        for group_name, matches in (
            result.matched_required_groups.items()
        ):
            print(
                f"GROUP {group_name}: {matches}"
            )

        if result.matched_include:
            print(
                f"INCLUDE: {result.matched_include}"
            )

        if result.matched_context:
            print(
                f"CONTEXT: {result.matched_context}"
            )

        if result.matched_priority:
            print(
                f"PRIORITY: {result.matched_priority}"
            )

        if result.matched_exclude:
            print(
                f"EXCLUDE: {result.matched_exclude}"
            )

        if article.doi:
            print(f"DOI: {article.doi}")

        if article.source_url:
            print(f"URL: {article.source_url}")


def run_profile(
    articles,
    filename,
):
    profile = load_profile(filename)

    counts, results = evaluate_profile(
        articles,
        profile,
    )

    print_results(
        profile,
        counts,
        results,
    )


def main():
    print("=" * 80)
    print("WATCHTOWER REAL-DATA FILTER TEST")
    print("=" * 80)

    articles = load_nature_articles()

    print(f"Nature articles loaded: {len(articles)}")

    if not articles:
        print("No Nature articles found in database.")
        return

    run_profile(
        articles,
        "automated_reviews.yaml",
    )

    run_profile(
        articles,
        "agentic_epidemiology.yaml",
    )


if __name__ == "__main__":
    main()