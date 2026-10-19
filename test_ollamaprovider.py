from models.llm_results import LLMResult
from providers.ollama_provider import (
    OllamaConnectionError,
    OllamaProvider,
    OllamaResponseError,
)


MODEL = "qwen3-light:latest"


SYSTEM_PROMPT = """
You are a scientific literature relevance classifier.

Determine whether the scientific article described by the user
is relevant to the requested research topic.

Return only the structured response requested by the JSON schema.

The confidence score must be between 0 and 1.

The reason must briefly explain the relevance decision.

The summary must briefly summarize the scientific content of
the article.
""".strip()


USER_PROMPT = """
Research topic:
Advanced artificial intelligence in epidemiology and public health.

Article title:
Large language models for infectious disease surveillance.

Article abstract:
This study evaluates the use of large language models to extract
epidemiological signals from public health reports for infectious
disease surveillance and outbreak detection.
""".strip()


def main():
    print("=" * 80)
    print("WATCHTOWER OLLAMA PROVIDER TEST")
    print("=" * 80)

    provider = OllamaProvider(
        model=MODEL,
        temperature=0.0,
    )

    print(f"Provider: {provider.get_provider_name()}")
    print(f"Model: {provider.get_model_name()}")
    print()

    try:
        result = provider.generate_structured(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            output_model=LLMResult,
        )

    except OllamaConnectionError as exc:
        print("OLLAMA CONNECTION ERROR")
        print(exc)
        return

    except OllamaResponseError as exc:
        print("OLLAMA RESPONSE ERROR")
        print(exc)
        return

    print("Structured response received and validated.")
    print()

    print(f"Relevant:   {result.relevant}")
    print(f"Confidence: {result.confidence}")
    print(f"Reason:     {result.reason}")
    print(f"Summary:    {result.summary}")

    print()
    print("Raw validated data:")
    print(result.model_dump())

    print()
    print("=" * 80)
    print("TEST COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    main()