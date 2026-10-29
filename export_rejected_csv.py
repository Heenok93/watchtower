"""Export deterministic Watchtower rejections from watchtower.db to CSV.

Examples (run from the Watchtower project root):
    python export_rejected_csv.py
    python export_rejected_csv.py --topic agentic_health_ai
    python export_rejected_csv.py --topic laboratory_ai --output laboratory_rejected.csv

The script only reads the database; it does not modify it.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from storage.database import get_connection


DEFAULT_OUTPUT = "watchtower_rejected.csv"

FIELDS = [
    "article_id",
    "topic_id",
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
    "collected_at",
    "score",
    "decision",
    "required_groups_satisfied",
    "matched_include",
    "matched_context",
    "matched_priority",
    "matched_exclude",
    "matched_required_groups",
    "processed_at",
]


def csv_safe(value: Any) -> Any:
    """Avoid interpreting text beginning with formula markers as a spreadsheet formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def json_text(value: Any, default: Any) -> str:
    if value is None or value == "":
        value = default
    elif isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def export_rejected(output_path: Path, topic_id: str | None = None) -> int:
    sql = """
        SELECT
            a.id AS article_id,
            r.topic_id,
            a.title,
            a.abstract,
            a.authors,
            a.publication_date,
            a.journal,
            a.source,
            a.content_type,
            a.doi,
            a.pmid,
            a.source_url,
            a.collected_at,
            r.score,
            r.decision,
            r.required_groups_satisfied,
            r.matched_include,
            r.matched_context,
            r.matched_priority,
            r.matched_exclude,
            r.matched_required_groups,
            r.processed_at
        FROM article_topic_results AS r
        JOIN articles AS a ON a.id = r.article_id
        WHERE r.decision = 'reject'
    """
    params: tuple[str, ...] = ()
    if topic_id:
        sql += " AND r.topic_id = ?"
        params = (topic_id,)
    sql += " ORDER BY r.topic_id, a.id"

    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            for column, default in (
                ("matched_include", []),
                ("matched_context", []),
                ("matched_priority", []),
                ("matched_exclude", []),
                ("matched_required_groups", {}),
            ):
                item[column] = json_text(item.get(column), default)
            writer.writerow({key: csv_safe(value) for key, value in item.items()})

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export deterministic rejections from Watchtower's SQLite database to CSV."
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Optional topic/profile ID, e.g. agentic_health_ai. Without it, exports rejects for all topics.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output CSV path (default: {DEFAULT_OUTPUT}).",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    try:
        count = export_rejected(output_path, args.topic)
    except Exception as exc:
        raise SystemExit(
            f"Export failed: {exc}\n"
            "Run this script from the Watchtower project root and check that storage/watchtower.db exists."
        ) from exc

    print("=" * 72)
    print("WATCHTOWER — DETERMINISTIC REJECTIONS EXPORT")
    print(f"Topic:       {args.topic or 'ALL'}")
    print(f"Rejected rows: {count}")
    print(f"CSV written: {output_path.resolve()}")
    print("Database was not modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
