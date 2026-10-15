import json

from storage.topic_result_repository import (
    count_topic_results,
    get_reviewable_topic_results,
    get_topic_result_counts,
)


def parse_json(value, default):
    if not value:
        return default

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def print_summary():
    rows = get_topic_result_counts()

    print("=" * 80)
    print("WATCHTOWER FILTER RESULTS")
    print("=" * 80)

    print(
        "Total persisted results: "
        f"{count_topic_results()}"
    )

    if not rows:
        print("No filter results found.")
        return

    current_topic = None

    for row in rows:
        topic_id = row["topic_id"]

        if topic_id != current_topic:
            print()
            print(f"TOPIC: {topic_id}")
            current_topic = topic_id

        print(
            f"  {row['decision']}: "
            f"{row['count']}"
        )


def print_reviewable_results():
    rows = get_reviewable_topic_results()

    print()
    print("=" * 80)
    print("CANDIDATES AND LLM REVIEW")
    print("=" * 80)

    if not rows:
        print("No reviewable results found.")
        return

    current_topic = None

    for row in rows:
        topic_id = row["topic_id"]

        if topic_id != current_topic:
            print()
            print("-" * 80)
            print(f"TOPIC: {topic_id}")
            print("-" * 80)
            current_topic = topic_id

        matched_include = parse_json(
            row["matched_include"],
            [],
        )

        matched_context = parse_json(
            row["matched_context"],
            [],
        )

        matched_priority = parse_json(
            row["matched_priority"],
            [],
        )

        matched_exclude = parse_json(
            row["matched_exclude"],
            [],
        )

        matched_required_groups = parse_json(
            row["matched_required_groups"],
            {},
        )

        required_groups_ok = bool(
            row["required_groups_satisfied"]
        )

        print()
        print(f"ARTICLE ID: {row['article_id']}")
        print(f"TITLE: {row['title']}")
        print(f"SOURCE: {row['source']}")
        print(f"DECISION: {row['decision']}")
        print(f"SCORE: {row['score']}")

        print(
            "REQUIRED GROUPS OK: "
            f"{required_groups_ok}"
        )

        for group_name, matches in (
            matched_required_groups.items()
        ):
            print(
                f"GROUP {group_name}: "
                f"{matches}"
            )

        if matched_include:
            print(
                f"INCLUDE: "
                f"{matched_include}"
            )

        if matched_context:
            print(
                f"CONTEXT: "
                f"{matched_context}"
            )

        if matched_priority:
            print(
                f"PRIORITY: "
                f"{matched_priority}"
            )

        if matched_exclude:
            print(
                f"EXCLUDE: "
                f"{matched_exclude}"
            )

        if row["doi"]:
            print(f"DOI: {row['doi']}")

        if row["source_url"]:
            print(
                f"URL: {row['source_url']}"
            )

        print(
            f"PROCESSED AT: "
            f"{row['processed_at']}"
        )


def main():
    print_summary()
    print_reviewable_results()


if __name__ == "__main__":
    main()