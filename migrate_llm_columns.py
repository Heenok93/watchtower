import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent / "storage" / "watchtower.db"


LLM_COLUMNS = {
    "llm_decision": "TEXT",
    "llm_confidence": "REAL",
    "llm_reason": "TEXT",
    "llm_summary": "TEXT",
    "llm_provider": "TEXT",
    "llm_model": "TEXT",
    "llm_processed_at": "TEXT",
}


def main():
    print(f"Database: {DB_PATH}")

    connection = sqlite3.connect(DB_PATH)

    try:
        cursor = connection.cursor()

        cursor.execute(
            "PRAGMA table_info(article_topic_results)"
        )

        existing_columns = {
            row[1]
            for row in cursor.fetchall()
        }

        for column_name, column_type in LLM_COLUMNS.items():
            if column_name in existing_columns:
                print(f"Already exists: {column_name}")
                continue

            cursor.execute(
                f"""
                ALTER TABLE article_topic_results
                ADD COLUMN {column_name} {column_type}
                """
            )

            print(f"Added: {column_name}")

        connection.commit()

    finally:
        connection.close()

    print()
    print("Migration completed.")


if __name__ == "__main__":
    main()