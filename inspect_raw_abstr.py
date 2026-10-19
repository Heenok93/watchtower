from collections import defaultdict

from storage.database import get_connection


SAMPLES_PER_SOURCE = 5


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
                publication_date,
                doi,
                source_url
            FROM articles
            WHERE abstract IS NOT NULL
              AND TRIM(abstract) != ''
            ORDER BY source, id DESC
            """
        ).fetchall()

    return rows


def main():
    print("=" * 80)
    print("WATCHTOWER RAW ABSTRACT INSPECTION")
    print("=" * 80)

    rows = get_articles()

    by_source = defaultdict(list)

    for row in rows:
        by_source[row["source"]].append(row)

    for source in sorted(by_source):
        articles = by_source[source][
            :SAMPLES_PER_SOURCE
        ]

        print()
        print("=" * 80)
        print(f"SOURCE: {source}")
        print("=" * 80)

        for index, row in enumerate(
            articles,
            start=1,
        ):
            abstract = row["abstract"]

            print()
            print("-" * 80)
            print(f"[{index}]")
            print("-" * 80)

            print(f"Article ID:   {row['id']}")
            print(f"Type:         {row['content_type']}")
            print(f"Title:        {row['title']}")
            print(f"Date:         {row['publication_date']}")
            print(f"DOI:          {row['doi']}")
            print(
                f"Length:       "
                f"{len(abstract)} characters"
            )

            print()
            print("RAW ABSTRACT")
            print("-" * 80)
            print(abstract)

            if row["source_url"]:
                print()
                print(f"URL: {row['source_url']}")

    print()
    print("=" * 80)
    print("END")
    print("=" * 80)


if __name__ == "__main__":
    main()