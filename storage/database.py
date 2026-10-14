from pathlib import Path
import sqlite3


DB_PATH = Path(__file__).resolve().parent / "watchtower.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
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

                collected_at TEXT NOT NULL,

                fingerprint TEXT,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_doi
            ON articles(doi)
            WHERE doi IS NOT NULL
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_pmid
            ON articles(pmid)
            WHERE pmid IS NOT NULL
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_source_url
            ON articles(source_url)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_fingerprint
            ON articles(fingerprint)
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

        conn.commit()