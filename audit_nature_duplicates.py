from storage.database import get_connection


def normalize_title(title):
    if not title:
        return ""

    return " ".join(
        title.lower().strip().split()
    )


def main():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                title,
                doi,
                source_url,
                publication_date,
                fingerprint,
                content_type,
                created_at
            FROM articles
            WHERE source = 'nature'
            ORDER BY id
            """
        ).fetchall()

    print("=" * 80)
    print("WATCHTOWER NATURE DUPLICATE AUDIT")
    print("=" * 80)
    print(f"Nature rows in database: {len(rows)}")
    print()

    by_title = {}

    for row in rows:
        key = normalize_title(row["title"])

        if not key:
            continue

        by_title.setdefault(
            key,
            [],
        ).append(row)

    duplicate_groups = {
        title: group
        for title, group in by_title.items()
        if len(group) > 1
    }

    duplicate_rows = sum(
        len(group) - 1
        for group in duplicate_groups.values()
    )

    print(
        f"Duplicate title groups: "
        f"{len(duplicate_groups)}"
    )

    print(
        f"Potential duplicate rows: "
        f"{duplicate_rows}"
    )

    print()

    for group_number, group in enumerate(
        duplicate_groups.values(),
        start=1,
    ):
        print("-" * 80)
        print(
            f"DUPLICATE GROUP {group_number}"
        )
        print("-" * 80)

        for row in group:
            print(f"ID:          {row['id']}")
            print(f"Title:       {row['title']}")
            print(f"DOI:         {row['doi']}")
            print(
                f"URL:         "
                f"{row['source_url']}"
            )
            print(
                f"Date:        "
                f"{row['publication_date']}"
            )
            print(
                f"Fingerprint: "
                f"{row['fingerprint']}"
            )
            print(
                f"Content type:"
                f" {row['content_type']}"
            )
            print(
                f"Created at:  "
                f"{row['created_at']}"
            )
            print()


if __name__ == "__main__":
    main()