from pathlib import Path

import yaml

from models.schemas import Article, TopicProfile
from processing.llm_classifier import classify_article
from providers.ollama_provider import (
    OllamaConnectionError,
    OllamaProvider,
    OllamaResponseError,
)


MODEL = "qwen3-light:latest"

PROFILE_PATH = (
    Path(__file__).parent
    / "config"
    / "topics"
    / "agentic_epidemiology.yaml"
)


def load_profile() -> TopicProfile:
    with open(PROFILE_PATH, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return TopicProfile.model_validate(data)


def run_test(
    label: str,
    article: Article,
    expected_relevant: bool,
    profile: TopicProfile,
    provider: OllamaProvider,
) -> bool:
    print()
    print("=" * 80)
    print(label)
    print("=" * 80)

    print(f"Title: {article.title}")
    print(f"Expected relevant: {expected_relevant}")
    print()

    try:
        result = classify_article(
            article=article,
            profile=profile,
            provider=provider,
        )

    except OllamaConnectionError as exc:
        print("OLLAMA CONNECTION ERROR")
        print(exc)
        return False

    except OllamaResponseError as exc:
        print("OLLAMA RESPONSE ERROR")
        print(exc)
        return False

    print(f"Relevant:   {result.relevant}")
    print(f"Confidence: {result.confidence}")
    print(f"Reason:     {result.reason}")
    print(f"Summary:    {result.summary}")
    print()

    passed = result.relevant == expected_relevant

    if passed:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")

    return passed


def main():
    print("=" * 80)
    print("WATCHTOWER LLM CLASSIFIER TEST")
    print("=" * 80)

    profile = load_profile()

    provider = OllamaProvider(
        model=MODEL,
        temperature=0.0,
    )

    print(f"Profile:  {profile.name}")
    print(f"Provider: {provider.get_provider_name()}")
    print(f"Model:    {provider.get_model_name()}")

    positive_article = Article(
        title=(
            "Large language models for infectious "
            "disease surveillance"
        ),
        abstract=(
            "This study evaluates the use of large language models "
            "to extract epidemiological signals from public health "
            "reports for infectious disease surveillance and "
            "outbreak detection."
        ),
        source="test",
    )

    negative_article = Article(
        title=(
            "Machine learning for personalized "
            "travel agent recommendations"
        ),
        abstract=(
            "This study develops a machine learning system for "
            "travel agents to recommend vacation destinations, "
            "hotels, and tourism services to customers."
        ),
        source="test",
    )

    positive_passed = run_test(
        label="TEST 1 - POSITIVE CASE",
        article=positive_article,
        expected_relevant=True,
        profile=profile,
        provider=provider,
    )

    negative_passed = run_test(
        label="TEST 2 - NEGATIVE CASE",
        article=negative_article,
        expected_relevant=False,
        profile=profile,
        provider=provider,
    )

    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    print(
        "Positive case:",
        "PASS" if positive_passed else "FAIL",
    )

    print(
        "Negative case:",
        "PASS" if negative_passed else "FAIL",
    )

    print()

    if positive_passed and negative_passed:
        print("ALL TESTS PASSED")
    else:
        print("ONE OR MORE TESTS FAILED")


if __name__ == "__main__":
    main()