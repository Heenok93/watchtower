from models.llm_results import LLMResult
from storage.database import get_connection
from storage.topic_result_repository import (
    get_llm_review_results,
    save_llm_result,
)


TEST_PROVIDER = "ollama"
TEST_MODEL = "qwen3-light:latest"


def reset_llm_result(article_id, topic_id):
    """
    Reset the LLM fields after the test so that the real
    article/topic pair remains available for future processing.
    """

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE article_topic_results
            SET
                llm_decision = NULL,
                llm_confidence = NULL,
                llm_reason = NULL,
                llm_summary = NULL,
                llm_provider = NULL,
                llm_model = NULL,
                llm_processed_at = NULL
            WHERE article_id = ?
              AND topic_id = ?
            """,
            (
                article_id,
                topic_id,
            ),
        )

        conn.commit()


def get_saved_result(article_id, topic_id):
    """
    Read back the deterministic and LLM fields for one
    article/topic pair.
    """

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                article_id,
                topic_id,
                decision,
                llm_decision,
                llm_confidence,
                llm_reason,
                llm_summary,
                llm_provider,
                llm_model,
                llm_processed_at
            FROM article_topic_results
            WHERE article_id = ?
              AND topic_id = ?
            """,
            (
                article_id,
                topic_id,
            ),
        ).fetchone()

    return row


def main():
    print("=" * 80)
    print("WATCHTOWER LLM PERSISTENCE TEST")
    print("=" * 80)

    review_results = get_llm_review_results(
        only_unprocessed=True
    )

    print(
        f"Unprocessed LLM review results: "
        f"{len(review_results)}"
    )
    print()

    if not review_results:
        print(
            "No unprocessed llm_review result "
            "available for testing."
        )
        return

    test_row = review_results[0]

    article_id = test_row["article_id"]
    topic_id = test_row["topic_id"]

    print("Selected test row:")
    print(f"Article ID: {article_id}")
    print(f"Topic ID:   {topic_id}")
    print(f"Title:      {test_row['title']}")
    print(f"Decision:   {test_row['decision']}")
    print()

    test_result = LLMResult(
        relevant=True,
        confidence=0.91,
        reason=(
            "Synthetic persistence test for Watchtower."
        ),
        summary=(
            "Synthetic summary used only to verify "
            "LLM result persistence."
        ),
    )

    try:
        print("Saving synthetic LLM result...")

        updated_rows = save_llm_result(
            article_id=article_id,
            topic_id=topic_id,
            result=test_result,
            provider_name=TEST_PROVIDER,
            model_name=TEST_MODEL,
        )

        print(f"Rows updated: {updated_rows}")
        print()

        if updated_rows != 1:
            print("RESULT: FAIL")
            print(
                "Expected exactly one llm_review row "
                "to be updated."
            )
            return

        saved = get_saved_result(
            article_id=article_id,
            topic_id=topic_id,
        )

        if saved is None:
            print("RESULT: FAIL")
            print("Saved row could not be read back.")
            return

        print("Persisted values:")
        print(f"Decision:       {saved['decision']}")
        print(f"LLM decision:   {saved['llm_decision']}")
        print(f"LLM confidence: {saved['llm_confidence']}")
        print(f"LLM provider:   {saved['llm_provider']}")
        print(f"LLM model:      {saved['llm_model']}")
        print(
            f"LLM processed:  "
            f"{saved['llm_processed_at']}"
        )
        print()

        checks = {
            "deterministic decision preserved":
                saved["decision"] == "llm_review",

            "LLM decision persisted":
                saved["llm_decision"] == "relevant",

            "LLM confidence persisted":
                saved["llm_confidence"] == 0.91,

            "LLM reason persisted":
                saved["llm_reason"]
                == test_result.reason,

            "LLM summary persisted":
                saved["llm_summary"]
                == test_result.summary,

            "LLM provider persisted":
                saved["llm_provider"]
                == TEST_PROVIDER,

            "LLM model persisted":
                saved["llm_model"]
                == TEST_MODEL,

            "LLM timestamp persisted":
                saved["llm_processed_at"]
                is not None,
        }

        print("Validation:")

        all_passed = True

        for name, passed in checks.items():
            status = "PASS" if passed else "FAIL"
            print(f"{status}: {name}")

            if not passed:
                all_passed = False

        print()

        remaining = get_llm_review_results(
            only_unprocessed=True
        )

        still_returned = any(
            row["article_id"] == article_id
            and row["topic_id"] == topic_id
            for row in remaining
        )

        if not still_returned:
            print(
                "PASS: processed row excluded from "
                "unprocessed LLM queue"
            )
        else:
            print(
                "FAIL: processed row still present in "
                "unprocessed LLM queue"
            )
            all_passed = False

        print()
        print("=" * 80)

        if all_passed:
            print("ALL PERSISTENCE TESTS PASSED")
        else:
            print("ONE OR MORE PERSISTENCE TESTS FAILED")

        print("=" * 80)

    finally:
        print()
        print("Cleaning up synthetic LLM result...")

        reset_llm_result(
            article_id=article_id,
            topic_id=topic_id,
        )

        restored = get_saved_result(
            article_id=article_id,
            topic_id=topic_id,
        )

        if (
            restored is not None
            and restored["decision"] == "llm_review"
            and restored["llm_processed_at"] is None
        ):
            print(
                "Test row restored successfully."
            )
        else:
            print(
                "WARNING: test row was not fully restored."
            )


if __name__ == "__main__":
    main()