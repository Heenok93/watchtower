"""Small, explicit, additive SQLite migration runner."""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _migration_008_classification_v2(conn: sqlite3.Connection) -> None:
    """Add version metadata to deterministic results and V2 classification stores."""
    _add_column_if_missing(conn, "article_topic_results", "profile_hash", "TEXT")
    _add_column_if_missing(conn, "article_topic_results", "profile_version", "TEXT")
    _add_column_if_missing(conn, "article_topic_results", "filter_engine_version", "TEXT")
    _add_column_if_missing(conn, "article_topic_results", "input_hash", "TEXT")

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS model_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        run_id TEXT NOT NULL,
        model_role TEXT NOT NULL CHECK (model_role IN ('system1', 'system2', 'other')),
        provider_name TEXT NOT NULL,
        model_name TEXT NOT NULL,
        model_version TEXT,
        prompt_version TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        taxonomy_version TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        scores_json TEXT NOT NULL,
        labels_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '{}',
        rationales_json TEXT NOT NULL DEFAULT '{}',
        raw_response_json TEXT,
        latency_ms INTEGER,
        input_tokens INTEGER,
        output_tokens INTEGER,
        status TEXT NOT NULL DEFAULT 'completed',
        created_at TEXT NOT NULL,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_model_predictions_article
        ON model_predictions(article_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_model_predictions_role_status
        ON model_predictions(model_role, status);
    CREATE INDEX IF NOT EXISTS idx_model_predictions_run
        ON model_predictions(run_id);

    CREATE TABLE IF NOT EXISTS article_classifications (
        article_id INTEGER PRIMARY KEY,
        scores_json TEXT NOT NULL,
        labels_json TEXT NOT NULL,
        adjustments_json TEXT NOT NULL DEFAULT '[]',
        taxonomy_version TEXT NOT NULL,
        system1_prediction_id INTEGER,
        system2_prediction_id INTEGER,
        review_status TEXT NOT NULL DEFAULT 'system1',
        revision INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
        FOREIGN KEY (system1_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (system2_prediction_id) REFERENCES model_predictions(id)
    );

    CREATE TABLE IF NOT EXISTS article_classification_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        scores_json TEXT NOT NULL,
        labels_json TEXT NOT NULL,
        adjustments_json TEXT NOT NULL DEFAULT '[]',
        taxonomy_version TEXT NOT NULL,
        system1_prediction_id INTEGER,
        system2_prediction_id INTEGER,
        review_status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
        FOREIGN KEY (system1_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (system2_prediction_id) REFERENCES model_predictions(id),
        UNIQUE(article_id, revision)
    );

    CREATE INDEX IF NOT EXISTS idx_classification_history_article
        ON article_classification_history(article_id, revision DESC);
    """)



def _migration_009_legacy_topic_llm_history(conn: sqlite3.Connection) -> None:
    """Preserve legacy per-topic LLM outputs before deterministic invalidation."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS article_topic_llm_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        topic_id TEXT NOT NULL,
        llm_decision TEXT,
        llm_confidence REAL,
        llm_reason TEXT,
        llm_summary TEXT,
        llm_provider TEXT,
        llm_model TEXT,
        llm_processed_at TEXT,
        invalidation_reason TEXT NOT NULL,
        archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_topic_llm_history_article
        ON article_topic_llm_history(article_id, topic_id, archived_at DESC);
    """)



def _migration_010_classification_queue(conn: sqlite3.Connection) -> None:
    """Persist the deduplicated article-level System 1/System 2 work queue."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS classification_queue (
        article_id INTEGER PRIMARY KEY,
        review_topic_ids_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'system1_done', 'system2_pending', 'completed', 'error', 'obsolete')),
        is_eligible INTEGER NOT NULL DEFAULT 1,
        input_hash TEXT NOT NULL,
        taxonomy_version TEXT NOT NULL,
        system1_prompt_version TEXT NOT NULL,
        system1_prediction_id INTEGER,
        system2_prediction_id INTEGER,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
        FOREIGN KEY (system1_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (system2_prediction_id) REFERENCES model_predictions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_classification_queue_status
        ON classification_queue(status, is_eligible, article_id);
    """)



def _migration_011_system2_queue_metadata(conn: sqlite3.Connection) -> None:
    """Persist System 2 routing provenance and retry metadata."""
    _add_column_if_missing(
        conn, "classification_queue", "system2_review_dimensions_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(conn, "classification_queue", "system2_calibration_version", "TEXT")
    _add_column_if_missing(
        conn, "classification_queue", "system2_attempts",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(conn, "classification_queue", "system2_last_attempt_at", "TEXT")
    _add_column_if_missing(conn, "classification_queue", "system2_completed_at", "TEXT")


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    applied = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    migrations = [
        (8, "classification_v2", _migration_008_classification_v2),
        (9, "legacy_topic_llm_history", _migration_009_legacy_topic_llm_history),
        (10, "classification_queue", _migration_010_classification_queue),
        (11, "system2_queue_metadata", _migration_011_system2_queue_metadata),
    ]
    for version, name, migration in migrations:
        if version in applied:
            continue
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
            (version, name),
        )
