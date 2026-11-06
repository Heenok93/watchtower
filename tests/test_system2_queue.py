import json
from datetime import datetime, timezone

from models.classification import CLASSIFICATION_DIMENSIONS
from processing.system2_routing import CALIBRATION_VERSION
from storage import database
from build_system2_queue import build_queue


def test_build_system2_queue_routes_once_and_persists_dimensions(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO articles (title, abstract, authors, source, content_type, collected_at)
               VALUES ('Test', 'Abstract', '[]', 'test', 'article', ?)""", (now,)
        )
        aid = cur.lastrowid
        digest = __import__("storage.classification_queue_repository", fromlist=["article_input_hash"]).article_input_hash("Test", "Abstract")
        conn.execute(
            """INSERT INTO model_predictions (
                article_id, run_id, model_role, provider_name, model_name, prompt_version,
                prompt_hash, taxonomy_version, input_hash, scores_json, labels_json,
                evidence_json, rationales_json, status, created_at
            ) VALUES (?, 'r1', 'system1', 'test', 'jev08', 'p1', 'h1', 'tax1', ?, ?, '{}', '{}', '{}', 'completed', ?)""",
            (aid, digest, json.dumps({name: (0.60 if name == "digital_health_ai" else 0.1) for name in CLASSIFICATION_DIMENSIONS}), now),
        )
        prediction_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO classification_queue (
                article_id, review_topic_ids_json, status, is_eligible, input_hash,
                taxonomy_version, system1_prompt_version, system1_prediction_id,
                created_at, updated_at
            ) VALUES (?, '[]', 'system1_done', 1, ?, 'tax1', 'p1', ?, ?, ?)""",
            (aid, digest, prediction_id, now, now),
        )
        conn.commit()

    first = build_queue()
    assert first["routed_articles"] == 1
    second = build_queue()
    assert second["already_routed"] == 1
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT status, system2_review_dimensions_json, system2_calibration_version FROM classification_queue WHERE article_id = ?",
            (aid,),
        ).fetchone()
    assert row["status"] == "system2_pending"
    assert json.loads(row["system2_review_dimensions_json"]) == ["digital_health_ai"]
    assert row["system2_calibration_version"] == CALIBRATION_VERSION
