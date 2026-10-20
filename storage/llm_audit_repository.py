"""Journal additionnel. Ne modifie aucune table existante."""
import hashlib
import json
from datetime import datetime, timezone
from storage.database import get_connection


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(sql, parameters=()):
    connection = get_connection()
    try:
        cursor = connection.execute(sql, parameters)
        connection.commit()
        return cursor.lastrowid
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_audit():
    _write('''CREATE TABLE IF NOT EXISTS llm_classification_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        run_id TEXT NOT NULL,
        article_id INTEGER NOT NULL,
        topic_id TEXT NOT NULL,
        status TEXT NOT NULL,
        provider_name TEXT NOT NULL,
        model_name TEXT NOT NULL,
        temperature REAL NOT NULL,
        prompt_version TEXT NOT NULL,
        prompt_hash TEXT NOT NULL,
        profile_hash TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        result_json TEXT,
        error TEXT
    )''')


def start_attempt(*, run_id, article_id, topic_id, provider_name,
                  model_name, temperature, prompt_version, payload):
    now = datetime.now(timezone.utc).isoformat()
    return _write('''INSERT INTO llm_classification_audit (
        created_at, updated_at, run_id, article_id, topic_id, status,
        provider_name, model_name, temperature, prompt_version,
        prompt_hash, profile_hash, input_hash, payload_json
    ) VALUES (?, ?, ?, ?, ?, 'started', ?, ?, ?, ?, ?, ?, ?, ?)''', (
        now, now, run_id, article_id, topic_id, provider_name, model_name,
        temperature, prompt_version,
        fingerprint(json_text({"system": payload["system_prompt"],
                               "user": payload["user_prompt"],
                               "schema": payload["output_schema"]})),
        fingerprint(json_text(payload["profile"])),
        fingerprint(json_text(payload["article_used"])), json_text(payload),
    ))


def update_attempt(attempt_id, status, *, result=None, error=None):
    if status not in {"generated", "persisted", "failed", "interrupted", "persistence_error"}:
        raise ValueError(f"Unknown audit status: {status}")
    _write('''UPDATE llm_classification_audit
        SET updated_at=?, status=?, result_json=COALESCE(?, result_json), error=?
        WHERE id=?''', (
        datetime.now(timezone.utc).isoformat(), status,
        None if result is None else json_text(result.model_dump(mode="json")),
        error, attempt_id,
    ))
