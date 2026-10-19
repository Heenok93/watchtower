import json
from collections import Counter, defaultdict

from storage.topic_result_repository import (
    get_llm_review_results,
)


def parse_json_field(value, default):
    """
    Safely decode JSON fields stored in SQLite.
    """

    if value is None:
        return default

    if isinstance(value, (list, dict)):
        return value

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def format_list(values):
    """
    Format a list for compact terminal output.
    """

    if not values:
        return "-"

    return ", ".join(str(value) for value in values)


def format_required_groups(value):
    """
    Format matched required groups stored as JSON.
    """

    groups = parse_json_field(
        value,
        {},
    )

    if not groups:
        return "-"

    parts = []

    for group_name, terms in groups.items():
        formatted_terms = format_list(terms)

        parts.append(
            f"{group_name}: [{formatted_terms}]"
        )

    return " | ".join(parts)


def print_queue_item(index, row):
    """
    Print one article/topic pair awaiting LLM review.
    """

    matched_include = parse_json_field(
        row["matched_include"],
        [],
    )

    matched_context = parse_json_field(
        row["matched_context"],
        [],
    )

    matched_priority = parse_json_field(
        row["matched_priority"],
        [],
    )

    matched_exclude = parse_json_field(
        row["matched_exclude"],
        [],
    )

    print()
    print("-" * 80)
    print(f"[{index}]")
    print("-" * 80)

    print(f"Article ID:   {row['article_id']}")
    print(f"Topic:        {row['topic_id']}")
    print(f"Source:       {row['source']}")

    content_type = (
        row["content_type"]
        if "content_type" in row.keys()
        else "unknown"
    )

    print(f"Content type: {content_type}")
    print(f"Title:        {row['title']}")
    print(f"Score:        {row['score']}")

    print(
        "Required groups satisfied: "
        f"{bool(row['required_groups_satisfied'])}"
    )

    print(
        "Matched include:  "
        f"{format_list(matched_include)}"
    )

    print(
        "Matched context:  "
        f"{format_list(matched_context)}"
    )

    print(
        "Matched priority: "
        f"{format_list(matched_priority)}"
    )

    print(
        "Matched exclude:  "
        f"{format_list(matched_exclude)}"
    )

    print(
        "Required groups:  "
        f"{format_required_groups(
            row['matched_required_groups']
        )}"
    )


def print_counter(title, counter):
    """
    Print a simple frequency table.
    """

    print()
    print(title)
    print("-" * len(title))

    if not counter:
        print("None")
        return

    for key, count in sorted(
        counter.items(),
        key=lambda item: (
            -item[1],
            str(item[0]),
        ),
    ):
        print(f"{str(key):35} {count}")


def main():
    print("=" * 80)
    print("WATCHTOWER LLM QUEUE INSPECTION")
    print("=" * 80)

    rows = get_llm_review_results(
        only_unprocessed=True
    )

    print(
        f"Unprocessed LLM review results: "
        f"{len(rows)}"
    )

    if not rows:
        print()
        print("Nothing waiting for LLM review.")
        return

    topic_counts = Counter()
    source_counts = Counter()
    content_type_counts = Counter()

    topic_source_counts = defaultdict(
        Counter
    )

    for index, row in enumerate(
        rows,
        start=1,
    ):
        topic_id = row["topic_id"]
        source = row["source"]

        content_type = (
            row["content_type"]
            if "content_type" in row.keys()
            else "unknown"
        )

        topic_counts[topic_id] += 1
        source_counts[source] += 1
        content_type_counts[content_type] += 1

        topic_source_counts[
            topic_id
        ][source] += 1

        print_queue_item(
            index=index,
            row=row,
        )

    print()
    print("=" * 80)
    print("QUEUE SUMMARY")
    print("=" * 80)

    print_counter(
        "By topic",
        topic_counts,
    )

    print_counter(
        "By source",
        source_counts,
    )

    print_counter(
        "By content type",
        content_type_counts,
    )

    print()
    print("By topic and source")
    print("-------------------")

    for topic_id in sorted(
        topic_source_counts
    ):
        print()
        print(topic_id)

        for source, count in sorted(
            topic_source_counts[
                topic_id
            ].items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        ):
            print(
                f"  {source:33} {count}"
            )

    print()
    print("=" * 80)
    print(
        f"TOTAL WAITING FOR LLM: {len(rows)}"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()