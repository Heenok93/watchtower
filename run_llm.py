from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import ValidationError

from models.schemas import Article, TopicProfile
from processing.llm_classifier import classify_article
from providers.ollama_provider import (
    OllamaConnectionError,
    OllamaProvider,
    OllamaResponseError,
)
from storage.topic_result_repository import (
    get_llm_review_results,
    save_llm_result,
)


MODEL = "qwen3-light:latest"
TEMPERATURE = 0.0

BASE_DIR = Path(__file__).resolve().parent
TOPICS_DIR = BASE_DIR / "config" / "topics"


def load_profile(topic_id):
    """
    Load and validate the YAML profile matching a topic ID.
    """

    profile_path = TOPICS_DIR / f"{topic_id}.yaml"

    if not profile_path.exists():
        raise FileNotFoundError(
            f"Topic profile not found: {profile_path}"
        )

    with open(
        profile_path,
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    return TopicProfile.model_validate(data)


def build_article(row):
    """
    Build the Article object required by the LLM classifier.

    The classifier currently uses the title and abstract.
    Source is also included because it belongs to the
    Watchtower Article model.
    """

    return Article(
        title=row["title"],
        abstract=row["abstract"],
        source=row["source"],
    )


def new_profile_stats():
    """
    Return an empty statistics structure for one topic profile.
    """

    return {
        "found": 0,
        "processed": 0,
        "relevant": 0,
        "not_relevant": 0,
        "errors": 0,
    }


def print_profile_summary(
    topic_id,
    stats,
):
    """
    Print the processing summary for one topic profile.
    """

    print()
    print("-" * 80)
    print(f"Profile: {topic_id}")
    print("-" * 80)
    print(f"Found:        {stats['found']}")
    print(f"Processed:    {stats['processed']}")
    print(f"Relevant:     {stats['relevant']}")
    print(
        f"Not relevant: "
        f"{stats['not_relevant']}"
    )
    print(f"Errors:       {stats['errors']}")


def main():
    print("=" * 80)
    print("WATCHTOWER LLM CLASSIFIER")
    print("=" * 80)

    provider = OllamaProvider(
        model=MODEL,
        temperature=TEMPERATURE,
    )

    provider_name = provider.get_provider_name()
    model_name = provider.get_model_name()

    print(f"Provider: {provider_name}")
    print(f"Model:    {model_name}")
    print()

    rows = get_llm_review_results(
        only_unprocessed=True
    )

    total_found = len(rows)

    print(
        f"Unprocessed LLM review results: "
        f"{total_found}"
    )

    if not rows:
        print()
        print("Nothing to process.")
        print("=" * 80)
        return

    profile_cache = {}

    profile_stats = defaultdict(
        new_profile_stats
    )

    total_processed = 0
    total_relevant = 0
    total_not_relevant = 0
    total_errors = 0

    for index, row in enumerate(
        rows,
        start=1,
    ):
        article_id = row["article_id"]
        topic_id = row["topic_id"]
        title = row["title"]

        profile_stats[topic_id]["found"] += 1

        print()
        print("-" * 80)
        print(
            f"[{index}/{total_found}] "
            f"Article ID: {article_id}"
        )
        print(f"Topic ID:   {topic_id}")
        print(f"Title:      {title}")
        print("-" * 80)

        try:
            if topic_id not in profile_cache:
                profile_cache[topic_id] = (
                    load_profile(topic_id)
                )

            profile = profile_cache[topic_id]

            article = build_article(row)

            result = classify_article(
                article=article,
                profile=profile,
                provider=provider,
            )

            updated_rows = save_llm_result(
                article_id=article_id,
                topic_id=topic_id,
                result=result,
                provider_name=provider_name,
                model_name=model_name,
            )

            if updated_rows != 1:
                raise RuntimeError(
                    "The LLM result was generated, "
                    "but exactly one llm_review row "
                    "was not updated."
                )

            llm_decision = (
                "relevant"
                if result.relevant
                else "not_relevant"
            )

            profile_stats[topic_id][
                "processed"
            ] += 1

            profile_stats[topic_id][
                llm_decision
            ] += 1

            total_processed += 1

            if result.relevant:
                total_relevant += 1
            else:
                total_not_relevant += 1

            print(f"Decision:   {llm_decision}")
            print(
                f"Confidence: "
                f"{result.confidence}"
            )
            print(f"Reason:     {result.reason}")
            print(f"Summary:    {result.summary}")
            print("Persistence: success")

        except FileNotFoundError as exc:
            profile_stats[topic_id]["errors"] += 1
            total_errors += 1

            print("PROFILE ERROR")
            print(exc)

        except ValidationError as exc:
            profile_stats[topic_id]["errors"] += 1
            total_errors += 1

            print("VALIDATION ERROR")
            print(exc)

        except OllamaConnectionError as exc:
            profile_stats[topic_id]["errors"] += 1
            total_errors += 1

            print("OLLAMA CONNECTION ERROR")
            print(exc)

        except OllamaResponseError as exc:
            profile_stats[topic_id]["errors"] += 1
            total_errors += 1

            print("OLLAMA RESPONSE ERROR")
            print(exc)

        except Exception as exc:
            profile_stats[topic_id]["errors"] += 1
            total_errors += 1

            print("PROCESSING ERROR")
            print(
                f"{type(exc).__name__}: {exc}"
            )

    print()
    print("=" * 80)
    print("RESULTS BY PROFILE")
    print("=" * 80)

    for topic_id in sorted(profile_stats):
        print_profile_summary(
            topic_id=topic_id,
            stats=profile_stats[topic_id],
        )

    print()
    print("=" * 80)
    print("TOTAL")
    print("=" * 80)
    print(f"Found:        {total_found}")
    print(f"Processed:    {total_processed}")
    print(f"Relevant:     {total_relevant}")
    print(
        f"Not relevant: "
        f"{total_not_relevant}"
    )
    print(f"Errors:       {total_errors}")
    print("=" * 80)


if __name__ == "__main__":
    main()