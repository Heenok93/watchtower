from pydantic import ValidationError

from models.llm_results import LLMResult


def main():
    print("Testing valid LLM result...")

    result = LLMResult(
        relevant=True,
        confidence=0.87,
        reason=(
            "The article applies a large language model "
            "to infectious disease surveillance."
        ),
        summary=(
            "The study evaluates an LLM-based approach "
            "for extracting surveillance information "
            "from public health reports."
        ),
    )

    print(result.model_dump())
    print()

    print("Testing invalid confidence...")

    try:
        LLMResult(
            relevant=True,
            confidence=1.5,
            reason="Relevant article.",
            summary="Test summary.",
        )
    except ValidationError as exc:
        print("Validation correctly rejected invalid confidence.")
        print(exc)
        print()

    print("Testing unexpected field...")

    try:
        LLMResult(
            relevant=True,
            confidence=0.8,
            reason="Relevant article.",
            summary="Test summary.",
            unexpected_field="should fail",
        )
    except ValidationError as exc:
        print("Validation correctly rejected unexpected field.")
        print(exc)


if __name__ == "__main__":
    main()