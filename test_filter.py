from pathlib import Path

import yaml

from models.schemas import (
    Article,
    TopicProfile,
)

from processing.deterministic_filter import (
    filter_article,
)


PROFILE_PATH = (
    Path(__file__).resolve().parent
    / "config"
    / "topics"
    / "automated_reviews.yaml"
)


def load_profile() -> TopicProfile:
    with open(
        PROFILE_PATH,
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    return TopicProfile.model_validate(data)


def print_result(
    article: Article,
    profile: TopicProfile,
) -> None:
    result = filter_article(
        article,
        profile,
    )

    print("=" * 70)
    print(f"TITLE: {article.title}")
    print(f"SCORE: {result.score}")
    print(f"DECISION: {result.decision}")

    print(
        f"REQUIRED GROUPS OK: "
        f"{result.required_groups_satisfied}"
    )

    for group_name, matches in (
        result.matched_required_groups.items()
    ):
        print(
            f"GROUP {group_name}: {matches}"
        )

    print(
        f"INCLUDE: {result.matched_include}"
    )

    print(
        f"CONTEXT: {result.matched_context}"
    )

    print(
        f"PRIORITY: {result.matched_priority}"
    )

    print(
        f"EXCLUDE: {result.matched_exclude}"
    )

    print()


def main():
    profile = load_profile()

    articles = [
        Article(
            title=(
                "Large language models for automated "
                "systematic review screening"
            ),
            abstract=(
                "We evaluate LLMs for title and abstract "
                "screening and study selection."
            ),
            source="test",
        ),

        Article(
            title=(
                "Machine learning for automated "
                "literature screening"
            ),
            abstract=(
                "Machine learning methods are evaluated "
                "for evidence synthesis workflows."
            ),
            source="test",
        ),

        Article(
            title=(
                "Systematic review of malaria prevalence"
            ),
            abstract=(
                "We conducted a systematic review and "
                "meta-analysis of malaria prevalence."
            ),
            source="test",
        ),

        Article(
            title=(
                "Foundation models for clinical "
                "decision support"
            ),
            abstract=(
                "Foundation models and deep learning "
                "are evaluated for clinical prediction."
            ),
            source="test",
        ),

        Article(
            title=(
                "Deep learning for automated data "
                "extraction in systematic reviews"
            ),
            abstract=(
                "A deep learning system automates "
                "evidence extraction from eligible studies."
            ),
            source="test",
        ),

        Article(
            title=(
                "Large language models in peer review"
            ),
            abstract=(
                "This study examines the use of LLMs "
                "during manuscript peer review."
            ),
            source="test",
        ),

        Article(
            title=(
                "Climate change and malaria: "
                "a systematic review"
            ),
            abstract=(
                "A systematic review of climate "
                "and malaria research."
            ),
            source="test",
        ),
    ]

    for article in articles:
        print_result(
            article,
            profile,
        )


if __name__ == "__main__":
    main()