import json
from collections import Counter, defaultdict

from storage.database import get_connection


def parse_json_field(value, default):
    if value is None:
        return default

    if isinstance(value, (list, dict)):
        return value

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def format_list(values):
    if not values:
        return "-"

    return ", ".join(
        str(value)
        for value in values
    )


def format_required_groups(value):
    groups = parse_json_field(
        value,
        {},
    )

    if not groups:
        return "-"

    parts = []

    for group_name, terms in groups.items():
        parts.append(
            f"{group_name}: "
            f"[{format_list(terms)}]"
        )

    return " | ".join(parts)


def get_llm_results():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                article_topic_results.id,
                article_topic_results.article_id,
                article_topic_results.topic_id,

                article_topic_results.score,
                article_topic_results.decision,
                article_topic_results.required_groups_satisfied,

                article_topic_results.matched_include,
                article_topic_results.matched_context,
                article_topic_results.matched_priority,
                article_topic_results.matched_exclude,
                article_topic_results.matched_required_groups,

                article_topic_results.llm_decision,
                article_topic_results.llm_confidence,
                article_topic_results.llm_reason,
                article_topic_results.llm_summary,
                article_topic_results.llm_provider,
                article_topic_results.llm_model,
                article_topic_results.llm_processed_at,

                articles.title,
                articles.abstract,
                articles.source,
                articles.source_url,
                articles.journal,
                articles.content_type,
                articles.doi,
                articles.publication_date

            FROM article_topic_results

            INNER JOIN articles
                ON articles.id =
                   article_topic_results.article_id

            WHERE
                article_topic_results.llm_processed_at
                IS NOT NULL

            ORDER BY
                article_topic_results.topic_id,
                article_topic_results.llm_decision DESC,
                article_topic_results.llm_confidence DESC,
                articles.title
            """
        ).fetchall()

    return rows


def print_result(index, row):
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

    print(f"Article ID:    {row['article_id']}")
    print(f"Topic:         {row['topic_id']}")
    print(f"Source:        {row['source']}")
    print(f"Content type:  {row['content_type']}")
    print(f"Journal:       {row['journal']}")
    print(f"Title:         {row['title']}")
    print(f"Date:          {row['publication_date']}")
    print(f"DOI:           {row['doi']}")
    print()

    print("DETERMINISTIC")
    print(f"Score:         {row['score']}")
    print(f"Decision:      {row['decision']}")
    print(
        "Required groups satisfied: "
        f"{bool(row['required_groups_satisfied'])}"
    )

    print(
        "Include:       "
        f"{format_list(matched_include)}"
    )

    print(
        "Context:       "
        f"{format_list(matched_context)}"
    )

    print(
        "Priority:      "
        f"{format_list(matched_priority)}"
    )

    print(
        "Exclude:       "
        f"{format_list(matched_exclude)}"
    )

    print(
        "Groups:        "
        f"{format_required_groups(
            row['matched_required_groups']
        )}"
    )

    print()
    print("LLM")

    print(
        f"Decision:      "
        f"{row['llm_decision']}"
    )

    print(
        f"Confidence:    "
        f"{row['llm_confidence']}"
    )

    print(
        f"Provider:      "
        f"{row['llm_provider']}"
    )

    print(
        f"Model:         "
        f"{row['llm_model']}"
    )

    print(
        f"Processed at:  "
        f"{row['llm_processed_at']}"
    )

    print()
    print(
        f"Reason:        "
        f"{row['llm_reason']}"
    )

    print(
        f"Summary:       "
        f"{row['llm_summary']}"
    )

    if row["source_url"]:
        print(
            f"URL:           "
            f"{row['source_url']}"
        )


def print_counter(title, counter):
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
        print(
            f"{str(key):35} {count}"
        )


def main():
    print("=" * 80)
    print("WATCHTOWER LLM RESULTS INSPECTION")
    print("=" * 80)

    rows = get_llm_results()

    print(
        f"Persisted LLM results: "
        f"{len(rows)}"
    )

    if not rows:
        print()
        print("No persisted LLM results.")
        return

    topic_counts = Counter()
    decision_counts = Counter()
    source_counts = Counter()
    content_type_counts = Counter()
    model_counts = Counter()

    source_decisions = defaultdict(
        Counter
    )

    topic_decisions = defaultdict(
        Counter
    )

    content_type_decisions = defaultdict(
        Counter
    )

    confidence_values = []

    relevant_rows = []
    not_relevant_rows = []

    for row in rows:
        topic_id = row["topic_id"]
        decision = row["llm_decision"]
        source = row["source"]
        content_type = row["content_type"]
        model = row["llm_model"]

        topic_counts[topic_id] += 1
        decision_counts[decision] += 1
        source_counts[source] += 1
        content_type_counts[content_type] += 1
        model_counts[model] += 1

        source_decisions[
            source
        ][decision] += 1

        topic_decisions[
            topic_id
        ][decision] += 1

        content_type_decisions[
            content_type
        ][decision] += 1

        if row["llm_confidence"] is not None:
            confidence_values.append(
                row["llm_confidence"]
            )

        if decision == "relevant":
            relevant_rows.append(row)
        else:
            not_relevant_rows.append(row)

    print()
    print("=" * 80)
    print("RELEVANT RESULTS")
    print("=" * 80)

    if not relevant_rows:
        print()
        print("No relevant results.")

    for index, row in enumerate(
        relevant_rows,
        start=1,
    ):
        print_result(
            index=index,
            row=row,
        )

    print()
    print("=" * 80)
    print("NOT RELEVANT RESULTS")
    print("=" * 80)

    if not not_relevant_rows:
        print()
        print("No not-relevant results.")

    for index, row in enumerate(
        not_relevant_rows,
        start=1,
    ):
        print_result(
            index=index,
            row=row,
        )

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print_counter(
        "By LLM decision",
        decision_counts,
    )

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

    print_counter(
        "By model",
        model_counts,
    )

    print()
    print("Decision by topic")
    print("-----------------")

    for topic_id in sorted(
        topic_decisions
    ):
        decisions = topic_decisions[
            topic_id
        ]

        print()
        print(topic_id)

        print(
            f"  relevant:     "
            f"{decisions['relevant']}"
        )

        print(
            f"  not_relevant: "
            f"{decisions['not_relevant']}"
        )

    print()
    print("Decision by source")
    print("------------------")

    for source in sorted(
        source_decisions
    ):
        decisions = source_decisions[
            source
        ]

        print()
        print(source)

        print(
            f"  relevant:     "
            f"{decisions['relevant']}"
        )

        print(
            f"  not_relevant: "
            f"{decisions['not_relevant']}"
        )

    print()
    print("Decision by content type")
    print("------------------------")

    for content_type in sorted(
        content_type_decisions
    ):
        decisions = content_type_decisions[
            content_type
        ]

        print()
        print(content_type)

        print(
            f"  relevant:     "
            f"{decisions['relevant']}"
        )

        print(
            f"  not_relevant: "
            f"{decisions['not_relevant']}"
        )

    if confidence_values:
        average_confidence = (
            sum(confidence_values)
            / len(confidence_values)
        )

        minimum_confidence = min(
            confidence_values
        )

        maximum_confidence = max(
            confidence_values
        )

        print()
        print("Confidence")
        print("----------")

        print(
            f"Average: "
            f"{average_confidence:.3f}"
        )

        print(
            f"Minimum: "
            f"{minimum_confidence:.3f}"
        )

        print(
            f"Maximum: "
            f"{maximum_confidence:.3f}"
        )

    print()
    print("=" * 80)
    print(
        f"TOTAL LLM RESULTS: {len(rows)}"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()