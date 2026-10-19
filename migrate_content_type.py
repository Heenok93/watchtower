from storage.database import get_connection


def main():
    with get_connection() as conn:
        columns = conn.execute(
            """
            PRAGMA table_info(articles)
            """
        ).fetchall()

        column_names = {
            row["name"]
            for row in columns
        }

        if "content_type" not in column_names:
            conn.execute(
                """
                ALTER TABLE articles
                ADD COLUMN content_type
                TEXT NOT NULL DEFAULT 'unknown'
                """
            )

            conn.commit()

            print("Added: content_type")
        else:
            print("Already exists: content_type")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_articles_content_type
            ON articles(content_type)
            """
        )

        conn.commit()

    print("Migration completed.")


if __name__ == "__main__":
    main()