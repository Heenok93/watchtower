from pathlib import Path
import sqlite3


def _ensure_unique_index(
    conn: sqlite3.Connection,
    *,
    index_name: str,
    column: str,
) -> None:
    """Create a partial unique index unless legacy duplicates need review.

    Existing duplicate rows are not deleted or merged automatically because
    doing so could discard article metadata or topic associations.
    """
    allowed_columns = {"doi", "pmid", "source_url", "fingerprint"}
    if column not in allowed_columns:
        raise ValueError(f"Unsupported article index column: {column}")

    duplicates = conn.execute(
        f"""
        SELECT {column}, COUNT(*) AS n
        FROM articles
        WHERE {column} IS NOT NULL AND TRIM({column}) <> ''
        GROUP BY {column}
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()

    conn.execute(f"DROP INDEX IF EXISTS {index_name}")
    if duplicates:
        print(
            f"WARNING: unique index {index_name} was not created: "
            f"duplicate values already exist in articles.{column}. "
            "Review and reconcile those records before retrying init_database()."
        )
        conn.execute(
            f"CREATE INDEX {index_name} ON articles({column})"
        )
        return

    conn.execute(
        f"""
        CREATE UNIQUE INDEX {index_name}
        ON articles({column})
        WHERE {column} IS NOT NULL AND TRIM({column}) <> ''
        """
    )


DB_PATH = Path(__file__).resolve().parent / "watchtower.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                title TEXT NOT NULL,
                abstract TEXT,
                authors TEXT,

                publication_date TEXT,

                doi TEXT,
                pmid TEXT,

                source TEXT NOT NULL,
                source_url TEXT,
                journal TEXT,
                content_type TEXT NOT NULL DEFAULT 'unknown',

                collected_at TEXT NOT NULL,

                fingerprint TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        _ensure_unique_index(
            conn,
            index_name="idx_articles_doi",
            column="doi",
        )

        _ensure_unique_index(
            conn,
            index_name="idx_articles_pmid",
            column="pmid",
        )

        _ensure_unique_index(
            conn,
            index_name="idx_articles_source_url",
            column="source_url",
        )

        _ensure_unique_index(
            conn,
            index_name="idx_articles_fingerprint",
            column="fingerprint",
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_content_type
            ON articles(content_type)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                source TEXT NOT NULL,

                started_at TEXT NOT NULL,
                finished_at TEXT,

                items_found INTEGER NOT NULL DEFAULT 0,
                items_inserted INTEGER NOT NULL DEFAULT 0,

                duplicates_doi INTEGER NOT NULL DEFAULT 0,
                duplicates_pmid INTEGER NOT NULL DEFAULT 0,
                duplicates_source_url INTEGER NOT NULL DEFAULT 0,
                duplicates_fingerprint INTEGER NOT NULL DEFAULT 0,

                errors INTEGER NOT NULL DEFAULT 0,

                status TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processing_runs_source
            ON processing_runs(source)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processing_runs_started_at
            ON processing_runs(started_at)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS article_topic_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                article_id INTEGER NOT NULL,
                topic_id TEXT NOT NULL,

                score INTEGER NOT NULL,
                decision TEXT NOT NULL,

                required_groups_satisfied INTEGER NOT NULL DEFAULT 0,

                matched_include TEXT NOT NULL DEFAULT '[]',
                matched_context TEXT NOT NULL DEFAULT '[]',
                matched_priority TEXT NOT NULL DEFAULT '[]',
                matched_exclude TEXT NOT NULL DEFAULT '[]',
                matched_required_groups TEXT NOT NULL DEFAULT '{}',

                processed_at TEXT NOT NULL,

                llm_decision TEXT,
                llm_confidence REAL,
                llm_reason TEXT,
                llm_summary TEXT,
                llm_provider TEXT,
                llm_model TEXT,
                llm_processed_at TEXT,

                FOREIGN KEY (article_id)
                    REFERENCES articles(id)
                    ON DELETE CASCADE,

                UNIQUE (article_id, topic_id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topic_results_topic
            ON article_topic_results(topic_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topic_results_decision
            ON article_topic_results(decision)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topic_results_article
            ON article_topic_results(article_id)
            """
        )

        conn.commit()