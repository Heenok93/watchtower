from collections import Counter, defaultdict
from unittest import result

from processing.abstract_quality import (
    assess_abstract_quality,
)
from storage.database import get_connection


SAMPLES_PER_QUALITY = 3


def get_articles():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                id,
                source,
                title,
                abstract
            FROM articles
            ORDER BY source, id
            """
        ).fetchall()


def main():
    print("=" * 80)
    print("WATCHTOWER ABSTRACT QUALITY TEST")
    print("=" * 80)

    rows = get_articles()

    source_counts = defaultdict(
        Counter
    )

    samples = defaultdict(
        lambda: defaultdict(list)
    )

    for row in rows:
        result = assess_abstract_quality(
        abstract=row["abstract"],
        title=row["title"],
  )

        quality = result.quality

        source = row["source"]

        source_counts[
            source
        ][quality] += 1

        if (
            len(samples[source][quality])
            < SAMPLES_PER_QUALITY
        ):
            samples[source][quality].append(
                row
            )

    print()
    print("SUMMARY BY SOURCE")
    print("=" * 80)

    for source in sorted(
        source_counts
    ):
        counts = source_counts[
            source
        ]

        total = sum(
            counts.values()
        )

        print()
        print(source)
        print("-" * 80)
        print(f"Total:         {total}")
        print(
            f"usable:        "
            f"{counts['usable']}"
        )
        print(
            f"short:         "
            f"{counts['short']}"
        )
        print(
            f"metadata_only: "
            f"{counts['metadata_only']}"
        )
        print(
            f"missing:       "
            f"{counts['missing']}"
        )

    print()
    print("=" * 80)
    print("EXAMPLES")
    print("=" * 80)

    for source in sorted(samples):
        print()
        print(f"SOURCE: {source}")
        print("=" * 80)

        for quality in [
            "usable",
            "short",
            "metadata_only",
            "missing",
        ]:
            rows_for_quality = (
                samples[source][quality]
            )

            if not rows_for_quality:
                continue

            print()
            print(
                f"QUALITY: {quality}"
            )
            print("-" * 80)

            for row in rows_for_quality:
                text = (
                    row["abstract"]
                    or ""
                )

                preview = " ".join(
                    text.split()
                )

                if len(preview) > 300:
                    preview = (
                        preview[:300]
                        + "..."
                    )

                print(
                    f"ID:    {row['id']}"
                )

                print(
                    f"Title: {row['title']}"
                )

                print(
                    f"Text:  {preview or '-'}"
                )

                print()

    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()