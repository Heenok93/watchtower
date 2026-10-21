"""WATCHTOWER - CSV export of reviewable articles.

Uses the same SQLite query and classification logic as
generate_digest.py.

No LLM calls, enrichment calls, or database writes.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from generate_digest import (
    article_url,
    classify_rows,
    clean_text,
    format_authors,
    format_date,
    human_topic_name,
    load_digest_rows,
    safe_json_loads,
)
from storage.database import get_connection


DEFAULT_OUTPUT = "watchtower_articles.csv"


CSV_FIELDS = [
    "article_id",
    "topic_id",
    "topic_name",
    "selection_status",
    "title",
    "abstract",
    "authors",
    "publication_date",
    "journal",
    "source",
    "content_type",
    "doi",
    "pmid",
    "source_url",
    "article_url",
    "collected_at",
    "filter_score",
    "deterministic_decision",
    "required_groups_satisfied",
    "matched_include",
    "matched_context",
    "matched_priority",
    "matched_exclude",
    "matched_required_groups",
    "filter_processed_at",
    "llm_decision",
    "llm_confidence",
    "llm_reason",
    "llm_summary",
    "llm_provider",
    "llm_model",
    "llm_processed_at",
    "review_status",
    "manual_notes",
]


def csv_safe(value: Any) -> Any:
    """
    Prevent spreadsheet applications from treating
    article text as formulas.
    """
    if isinstance(value, str):
        stripped = value.lstrip()

        if stripped.startswith(
            (
                "=",
                "+",
                "-",
                "@",
            )
        ):
            return "'" + value

    return value


def json_for_csv(
    value: Any,
    default: Any,
) -> str:
    """
    Normalize JSON database fields for CSV output.
    """
    parsed = safe_json_loads(
        value,
        default,
    )

    return json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
    )


def selection_status(
    row: dict[str, Any],
) -> str:
    if row["decision"] == "candidate":
        return "deterministic_candidate"

    if row["decision"] == "llm_review":
        decision = clean_text(
            row.get("llm_decision")
        ).lower()

        if decision == "relevant":
            return "llm_selected"

        if decision:
            return "llm_rejected"

        return "pending_llm_review"

    return clean_text(
        row.get("decision")
    )


def row_for_csv(
    row: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert one article/topic result into one
    spreadsheet-friendly CSV row.
    """
    return {
        "article_id": row["article_id"],
        "topic_id": row["topic_id"],
        "topic_name": human_topic_name(
            row["topic_id"]
        ),
        "selection_status": selection_status(
            row
        ),
        "title": clean_text(
            row.get("title")
        ),
        "abstract": clean_text(
            row.get("abstract")
        ),
        "authors": format_authors(
            row.get("authors")
        ),
        "publication_date": format_date(
            row.get("published_at")
        ),
        "journal": clean_text(
            row.get("journal")
        ),
        "source": clean_text(
            row.get("source")
        ),
        "content_type": clean_text(
            row.get("content_type")
        ),
        "doi": clean_text(
            row.get("doi")
        ),
        "pmid": clean_text(
            row.get("pmid")
        ),
        "source_url": clean_text(
            row.get("source_url")
        ),
        "article_url": article_url(
            row
        ),
        "collected_at": clean_text(
            row.get("collected_at")
        ),
        "filter_score": row.get(
            "score"
        ),
        "deterministic_decision": clean_text(
            row.get("decision")
        ),
        "required_groups_satisfied": row.get(
            "required_groups_satisfied"
        ),
        "matched_include": json_for_csv(
            row.get("matched_include"),
            [],
        ),
        "matched_context": json_for_csv(
            row.get("matched_context"),
            [],
        ),
        "matched_priority": json_for_csv(
            row.get("matched_priority"),
            [],
        ),
        "matched_exclude": json_for_csv(
            row.get("matched_exclude"),
            [],
        ),
        "matched_required_groups": json_for_csv(
            row.get("matched_required_groups"),
            {},
        ),
        "filter_processed_at": clean_text(
            row.get("processed_at")
        ),
        "llm_decision": clean_text(
            row.get("llm_decision")
        ),
        "llm_confidence": row.get(
            "llm_confidence"
        ),
        "llm_reason": clean_text(
            row.get("llm_reason")
        ),
        "llm_summary": clean_text(
            row.get("llm_summary")
        ),
        "llm_provider": clean_text(
            row.get("llm_provider")
        ),
        "llm_model": clean_text(
            row.get("llm_model")
        ),
        "llm_processed_at": clean_text(
            row.get("llm_processed_at")
        ),

        # Intentionally empty for manual review.
        "review_status": "",
        "manual_notes": "",
    }


def export_rows(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDS,
            delimiter=";",
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            normalized = row_for_csv(
                row
            )

            writer.writerow(
                {
                    key: csv_safe(value)
                    for key, value
                    in normalized.items()
                }
            )


def export_csv(
    output_path: Path,
    topic_id: str | None = None,
    include_llm_rejected: bool = False,
) -> dict[str, int]:
    connection = get_connection()

    try:
        rows = load_digest_rows(
            connection,
            topic_id,
        )
    finally:
        connection.close()

    (
        included,
        pending,
        rejected_by_llm,
    ) = classify_rows(rows)

    exported = list(included)
    exported.extend(pending)

    if include_llm_rejected:
        exported.extend(
            rejected_by_llm
        )

    exported.sort(
        key=lambda row: (
            clean_text(
                row.get("topic_id")
            ),
            selection_status(row),
            -int(row.get("score") or 0),
            int(row.get("article_id") or 0),
        )
    )

    export_rows(
        exported,
        output_path,
    )

    return {
        "included": len(included),
        "pending": len(pending),
        "rejected_by_llm": len(
            rejected_by_llm
        ),
        "exported": len(exported),
        "unique_articles": len(
            {
                row["article_id"]
                for row in exported
            }
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export Watchtower articles "
            "for manual review."
        )
    )

    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=(
            "Output CSV file "
            f"(default: {DEFAULT_OUTPUT})."
        ),
    )

    parser.add_argument(
        "--topic",
        default=None,
        help="Optional topic ID.",
    )

    parser.add_argument(
        "--include-llm-rejected",
        action="store_true",
        help=(
            "Include articles rejected "
            "by the LLM in the CSV."
        ),
    )

    args = parser.parse_args()

    output_path = Path(
        args.output
    )

    stats = export_csv(
        output_path=output_path,
        topic_id=args.topic,
        include_llm_rejected=(
            args.include_llm_rejected
        ),
    )

    print("=" * 80)
    print("WATCHTOWER CSV EXPORT")
    print("=" * 80)

    if args.topic:
        print(
            f"Topic:              "
            f"{args.topic}"
        )

    print(
        f"Included pairs:     "
        f"{stats['included']}"
    )

    print(
        f"Pending LLM review: "
        f"{stats['pending']}"
    )

    print(
        f"Rejected by LLM:    "
        f"{stats['rejected_by_llm']}"
    )

    print(
        f"Exported rows:      "
        f"{stats['exported']}"
    )

    print(
        f"Unique articles:    "
        f"{stats['unique_articles']}"
    )

    print(
        f"CSV written to:     "
        f"{output_path}"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()