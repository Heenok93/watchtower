import json
from collections import Counter
from statistics import median

from storage.database import get_connection


def has_text(value):
    return bool(
        value
        and str(value).strip()
    )


def get_authors_count(authors_json):
    if not authors_json:
        return 0

    try:
        authors = json.loads(authors_json)

        if isinstance(authors, list):
            return len(authors)

    except (json.JSONDecodeError, TypeError):
        pass

    return 0


def percentage(value, total):
    if total == 0:
        return 0.0

    return 100 * value / total


def get_articles():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                source,
                content_type,
                title,
                abstract,
                authors,
                publication_date,
                doi,
                pmid,
                source_url,
                journal
            FROM articles
            ORDER BY source, id
            """
        ).fetchall()

    return rows


def analyze_source(rows):
    total = len(rows)

    abstracts = [
        row["abstract"]
        for row in rows
        if has_text(row["abstract"])
    ]

    abstract_lengths = [
        len(abstract.strip())
        for abstract in abstracts
    ]

    with_doi = sum(
        has_text(row["doi"])
        for row in rows
    )

    with_pmid = sum(
        has_text(row["pmid"])
        for row in rows
    )

    with_date = sum(
        has_text(row["publication_date"])
        for row in rows
    )

    with_url = sum(
        has_text(row["source_url"])
        for row in rows
    )

    with_journal = sum(
        has_text(row["journal"])
        for row in rows
    )

    with_authors = sum(
        get_authors_count(row["authors"]) > 0
        for row in rows
    )

    content_types = Counter(
        row["content_type"] or "unknown"
        for row in rows
    )

    if abstract_lengths:
        avg_abstract_length = (
            sum(abstract_lengths)
            / len(abstract_lengths)
        )

        median_abstract_length = median(
            abstract_lengths
        )

        min_abstract_length = min(
            abstract_lengths
        )

        max_abstract_length = max(
            abstract_lengths
        )

    else:
        avg_abstract_length = 0
        median_abstract_length = 0
        min_abstract_length = 0
        max_abstract_length = 0

    return {
        "total": total,
        "abstracts": len(abstracts),
        "with_doi": with_doi,
        "with_pmid": with_pmid,
        "with_date": with_date,
        "with_url": with_url,
        "with_journal": with_journal,
        "with_authors": with_authors,
        "avg_abstract_length": avg_abstract_length,
        "median_abstract_length": median_abstract_length,
        "min_abstract_length": min_abstract_length,
        "max_abstract_length": max_abstract_length,
        "content_types": content_types,
    }


def print_metric(
    label,
    value,
    total,
):
    pct = percentage(
        value,
        total,
    )

    print(
        f"{label:<18}"
        f"{value:>5} / {total:<5}"
        f" ({pct:>5.1f}%)"
    )


def print_source_report(
    source,
    stats,
):
    total = stats["total"]

    print()
    print("=" * 80)
    print(source)
    print("=" * 80)

    print(f"Articles:          {total}")
    print()

    print("METADATA COVERAGE")
    print("-" * 80)

    print_metric(
        "Abstract:",
        stats["abstracts"],
        total,
    )

    print_metric(
        "Authors:",
        stats["with_authors"],
        total,
    )

    print_metric(
        "Date:",
        stats["with_date"],
        total,
    )

    print_metric(
        "DOI:",
        stats["with_doi"],
        total,
    )

    print_metric(
        "PMID:",
        stats["with_pmid"],
        total,
    )

    print_metric(
        "Source URL:",
        stats["with_url"],
        total,
    )

    print_metric(
        "Journal:",
        stats["with_journal"],
        total,
    )

    print()
    print("ABSTRACT LENGTH")
    print("-" * 80)

    print(
        "Average: "
        f"{stats['avg_abstract_length']:.0f} characters"
    )

    print(
        "Median:  "
        f"{stats['median_abstract_length']:.0f} characters"
    )

    print(
        "Minimum: "
        f"{stats['min_abstract_length']} characters"
    )

    print(
        "Maximum: "
        f"{stats['max_abstract_length']} characters"
    )

    print()
    print("CONTENT TYPES")
    print("-" * 80)

    for content_type, count in sorted(
        stats["content_types"].items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    ):
        print(
            f"{content_type:<20} {count}"
        )


def main():
    print("=" * 80)
    print("WATCHTOWER SOURCE QUALITY")
    print("=" * 80)

    rows = get_articles()

    print(f"Total articles: {len(rows)}")

    if not rows:
        print("No articles found.")
        return

    by_source = {}

    for row in rows:
        source = row["source"]

        if source not in by_source:
            by_source[source] = []

        by_source[source].append(row)

    source_stats = {}

    for source in sorted(by_source):
        stats = analyze_source(
            by_source[source]
        )

        source_stats[source] = stats

        print_source_report(
            source=source,
            stats=stats,
        )

    print()
    print("=" * 80)
    print("COMPACT COMPARISON")
    print("=" * 80)

    header = (
        f"{'Source':<28}"
        f"{'N':>6}"
        f"{'Abs%':>8}"
        f"{'Auth%':>8}"
        f"{'Date%':>8}"
        f"{'DOI%':>8}"
        f"{'AvgAbs':>9}"
    )

    print(header)
    print("-" * len(header))

    for source in sorted(source_stats):
        stats = source_stats[source]
        total = stats["total"]

        abstract_pct = percentage(
            stats["abstracts"],
            total,
        )

        authors_pct = percentage(
            stats["with_authors"],
            total,
        )

        date_pct = percentage(
            stats["with_date"],
            total,
        )

        doi_pct = percentage(
            stats["with_doi"],
            total,
        )

        print(
            f"{source:<28}"
            f"{total:>6}"
            f"{abstract_pct:>7.1f}%"
            f"{authors_pct:>7.1f}%"
            f"{date_pct:>7.1f}%"
            f"{doi_pct:>7.1f}%"
            f"{stats['avg_abstract_length']:>9.0f}"
        )

    print()
    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()