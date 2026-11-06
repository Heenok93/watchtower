import json
import sqlite3
from datetime import datetime, timezone

from storage import database
from processing.consolidation import consolidate
from adjudicate_article import adjudicate
from models.classification import CLASSIFICATION_DIMENSIONS


def _prediction(scores, labels, role, input_hash="hash"):
    return {
        "article_id": 1, "run_id": "test-run", "model_role": role,
        "provider_name": "test", "model_name": "test-model",
        "model_version": None, "prompt_version": "test-v1", "prompt_hash": "ph",
        "taxonomy_version": "watchtower_v2_frozen", "input_hash": input_hash,
        "scores_json": json.dumps(scores), "labels_json": json.dumps(labels),
        "evidence_json": "{}", "rationales_json": "{}", "raw_response_json": "{}",
        "latency_ms": 1, "input_tokens": 1, "output_tokens": 1,
        "status": "completed", "created_at": datetime.now(timezone.utc).isoformat(),
    }


def test_consolidation_then_manual_upsert_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    scores = {d: 0.1 for d in CLASSIFICATION_DIMENSIONS}
    scores.update({"agentic_ai_health": 0.52, "digital_health_ai": 0.60,
                   "drug_development_ai": 0.82})
    labels = {d: False for d in CLASSIFICATION_DIMENSIONS}
    s2_labels = dict(labels)
    s2_labels.update({"agentic_ai_health": True, "digital_health_ai": False,
                      "drug_development_ai": True})
    with database.get_connection() as conn:
        conn.execute("""INSERT INTO articles(title,source,content_type,collected_at)
                        VALUES ('Test article','test','journal','2026-11-06')""")
        p1 = _prediction(scores, labels, "system1")
        cur = conn.execute("""INSERT INTO model_predictions (
            article_id,run_id,model_role,provider_name,model_name,model_version,
            prompt_version,prompt_hash,taxonomy_version,input_hash,scores_json,
            labels_json,evidence_json,rationales_json,raw_response_json,latency_ms,
            input_tokens,output_tokens,status,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(p1.values()))
        p1id = cur.lastrowid
        p2 = _prediction({d: float(v) for d,v in s2_labels.items()}, s2_labels, "system2")
        p2["run_id"] = "test-run-2"
        cur = conn.execute("""INSERT INTO model_predictions (
            article_id,run_id,model_role,provider_name,model_name,model_version,
            prompt_version,prompt_hash,taxonomy_version,input_hash,scores_json,
            labels_json,evidence_json,rationales_json,raw_response_json,latency_ms,
            input_tokens,output_tokens,status,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(p2.values()))
        p2id = cur.lastrowid
        conn.execute("""INSERT INTO classification_queue (
            article_id,review_topic_ids_json,status,is_eligible,input_hash,taxonomy_version,
            system1_prompt_version,system1_prediction_id,system2_prediction_id,
            system2_review_dimensions_json,system2_calibration_version,created_at,updated_at
        ) VALUES (1,'[]','system2_pending',1,'hash','watchtower_v2_frozen','s1',?,?,?,
                  'calibration',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                     (p1id,p2id,json.dumps(["agentic_ai_health","digital_health_ai","drug_development_ai"])))
        conn.commit()

    result = consolidate()
    assert result["consolidated"] == 1
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM article_classifications WHERE article_id=1").fetchone()
        assert json.loads(row["labels_json"])["digital_health_ai"] is False
        assert json.loads(row["labels_json"])["drug_development_ai"] is True
        assert row["review_status"] == "final"
        first_revision = row["revision"]

    revision = adjudicate(article_id=1, dimension="digital_health_ai",
                          decision="true", reason="Human reviewer confirms a central digital-health workflow.")
    assert revision == first_revision + 1
    # Re-running consolidation must not erase the human override or create a new revision.
    consolidate()
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM article_classifications WHERE article_id=1").fetchone()
        assert json.loads(row["labels_json"])["digital_health_ai"] is True
        assert row["revision"] == revision
        assert row["review_status"] == "final"
        assert conn.execute("SELECT COUNT(*) FROM article_classification_history WHERE article_id=1").fetchone()[0] == 2


def test_pending_system2_does_not_block_other_finalization(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    scores = {d: 0.1 for d in CLASSIFICATION_DIMENSIONS}
    labels = {d: False for d in CLASSIFICATION_DIMENSIONS}
    with database.get_connection() as conn:
        conn.execute("INSERT INTO articles(title,source,content_type,collected_at) VALUES ('Pending','test','journal','2026-11-06')")
        p = _prediction(scores, labels, "system1")
        cur = conn.execute("""INSERT INTO model_predictions (
            article_id,run_id,model_role,provider_name,model_name,model_version,
            prompt_version,prompt_hash,taxonomy_version,input_hash,scores_json,
            labels_json,evidence_json,rationales_json,raw_response_json,latency_ms,
            input_tokens,output_tokens,status,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(p.values()))
        conn.execute("""INSERT INTO classification_queue (
            article_id,review_topic_ids_json,status,is_eligible,input_hash,taxonomy_version,
            system1_prompt_version,system1_prediction_id,system2_review_dimensions_json,
            created_at,updated_at
        ) VALUES (1,'[]','system2_pending',1,'hash','watchtower_v2_frozen','s1',?,
                  '["digital_health_ai"]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""", (cur.lastrowid,))
        conn.commit()
    result = consolidate(allow_pending_system2=True)
    assert result["consolidated"] == 0
    assert result["skipped_system2_pending"] == 1


def test_digest_and_export_read_only_eligible_consolidated_articles(tmp_path, monkeypatch):
    from generate_digest import generate_digest
    from export_classifications import export_classifications
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test-outputs.db")
    database.init_database()
    labels = {d: False for d in CLASSIFICATION_DIMENSIONS}
    labels["health_relevant"] = True
    scores = {d: 0.0 for d in CLASSIFICATION_DIMENSIONS}
    with database.get_connection() as conn:
        conn.execute("""INSERT INTO articles(title,abstract,source,content_type,collected_at)
                        VALUES ('Digest article','An abstract','test','journal','2026-11-06')""")
        conn.execute("""INSERT INTO classification_queue (
            article_id,review_topic_ids_json,status,is_eligible,input_hash,taxonomy_version,
            system1_prompt_version,created_at,updated_at
        ) VALUES (1,'["profile_a"]','completed',1,'hash','watchtower_v2_frozen','s1',
                  CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""")
        conn.execute("""INSERT INTO article_classifications (
            article_id,scores_json,labels_json,adjustments_json,taxonomy_version,
            review_status,revision,updated_at
        ) VALUES (1,?,?, '[]','watchtower_v2_frozen','final',1,CURRENT_TIMESTAMP)""",
                     (json.dumps(scores),json.dumps(labels)))
        conn.commit()
    digest = generate_digest(tmp_path / "digest.md")
    csv_path = export_classifications(tmp_path / "export.csv")
    assert "Digest article" in digest.read_text()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "health_relevant_label" in content
    assert "profile_a" in content
