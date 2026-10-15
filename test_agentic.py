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
    / "agentic_epidemiology.yaml"
)


def load_profile():
    with open(
        PROFILE_PATH,
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    return TopicProfile.model_validate(data)


def print_result(
    article,
    profile,
):
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
                "Large language models for infectious "
                "disease surveillance"
            ),
            abstract=(
                "We evaluate large language models "
                "for public health surveillance and "
                "early warning of infectious disease "
                "outbreaks."
            ),
            source="test",
        ),

        Article(
            title=(
                "Agentic AI for outbreak detection "
                "and epidemic intelligence"
            ),
            abstract=(
                "AI agents are evaluated for automated "
                "outbreak detection and public health "
                "epidemic intelligence."
            ),
            source="test",
        ),

        Article(
            title=(
                "Deep learning for infectious "
                "disease surveillance"
            ),
            abstract=(
                "Deep learning methods are evaluated "
                "for epidemiological surveillance of "
                "infectious diseases."
            ),
            source="test",
        ),

        Article(
            title=(
                "Machine learning for public health "
                "surveillance"
            ),
            abstract=(
                "Machine learning methods are applied "
                "to disease surveillance and outbreak "
                "detection."
            ),
            source="test",
        ),

        Article(
            title=(
                "Foundation models for protein "
                "structure prediction"
            ),
            abstract=(
                "Foundation models and transformers "
                "are used for protein structure "
                "prediction."
            ),
            source="test",
        ),

        Article(
            title=(
                "Epidemiology of dengue outbreaks "
                "in Brazil"
            ),
            abstract=(
                "We describe the epidemiology of "
                "dengue outbreaks using routine "
                "surveillance data."
            ),
            source="test",
        ),

        Article(
            title=(
                "Large language models for clinical "
                "decision support"
            ),
            abstract=(
                "Large language models are evaluated "
                "for clinical decision support in "
                "hospital medicine."
            ),
            source="test",
        ),

        Article(
            title=(
                "Generative AI for epidemic "
                "early warning"
            ),
            abstract=(
                "Generative AI is evaluated for "
                "epidemic surveillance and early "
                "warning in public health."
            ),
            source="test",
        ),

        Article(
            title=(
                "AI agents for infectious disease "
                "outbreak response"
            ),
            abstract=(
                "Autonomous agents support outbreak "
                "response and infectious disease "
                "surveillance."
            ),
            source="test",
        ),

        Article(
            title=(
                "Travel agents and public health "
                "requirements"
            ),
            abstract=(
                "Travel agents provide information "
                "about international public health "
                "requirements."
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