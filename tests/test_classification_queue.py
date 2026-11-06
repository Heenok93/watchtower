from datetime import datetime, timezone

from storage import database
from storage.classification_queue_repository import (
    build_classification_queue, get_pending_classification_rows,
    mark_queue_result, queue_status_counts,
)


def _insert_article_and_reviews(conn, *, abstract="abstract", topics=("topic_a", "topic_b")):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO articles (title, abstract, authors, source, content_type, collected_at)
           VALUES (?, ?, '[]', 'test', 'article', ?)""",
        ("Test article", abstract, now),
    )
    aid = cur.lastrowid
    for topic in topics:
        conn.execute(
            """INSERT INTO article_topic_results (
                article_id, topic_id, score, decision, processed_at
            ) VALUES (?, ?, 3, 'llm_review', ?)""",
            (aid, topic, now),
        )
    conn.commit()
    return aid


def test_queue_deduplicates_article_and_preserves_trigger_topics(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    with database.get_connection() as conn:
        aid = _insert_article_and_reviews(conn)

    result = build_classification_queue(taxonomy_version="tax-v1", prompt_version="p-v1")
    rows = get_pending_classification_rows()
    assert result["eligible_articles"] == 1
    assert result["inserted"] == 1
    assert len(rows) == 1
    assert rows[0]["article_id"] == aid
    assert rows[0]["review_topic_ids_json"] == '["topic_a", "topic_b"]'


def test_queue_reuses_completed_prediction_when_only_provenance_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    with database.get_connection() as conn:
        aid = _insert_article_and_reviews(conn, topics=("topic_a",))

    build_classification_queue(taxonomy_version="tax-v1", prompt_version="p-v1")
    mark_queue_result(aid, status="system1_done", prediction_id=None)
    with database.get_connection() as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO article_topic_results (
                article_id, topic_id, score, decision, processed_at
            ) VALUES (?, 'topic_b', 4, 'llm_review', ?)""",
            (aid, now),
        )
        conn.commit()

    result = build_classification_queue(taxonomy_version="tax-v1", prompt_version="p-v1")
    row = get_pending_classification_rows()  # system1_done is not pending
    assert result["reused"] == 1
    assert row == []
    assert queue_status_counts()["system1_done"] == 1
    with database.get_connection() as conn:
        saved = conn.execute(
            "SELECT review_topic_ids_json FROM classification_queue WHERE article_id = ?", (aid,)
        ).fetchone()
    assert saved[0] == '["topic_a", "topic_b"]'


def test_queue_resets_when_article_text_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    with database.get_connection() as conn:
        aid = _insert_article_and_reviews(conn)
    build_classification_queue(taxonomy_version="tax-v1", prompt_version="p-v1")
    mark_queue_result(aid, status="system1_done")
    with database.get_connection() as conn:
        conn.execute("UPDATE articles SET abstract = 'changed' WHERE id = ?", (aid,))
        conn.commit()
    result = build_classification_queue(taxonomy_version="tax-v1", prompt_version="p-v1")
    assert result["updated"] == 1
    assert len(get_pending_classification_rows()) == 1


def test_system1_parses_all_eight_noul_scores_and_persists_raw_prediction(tmp_path, monkeypatch):
    import json
    from io import BytesIO
    from unittest.mock import patch

    from processing import system1_classifier
    from storage.classification_repository import list_model_predictions, get_current_classification

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_database()
    with database.get_connection() as conn:
        aid = _insert_article_and_reviews(conn, topics=("topic_a",))

    scores = {name: 0.7 if name == "digital_health_ai" else 0.1
              for name in system1_classifier.DIMENSIONS}
    envelope = {
        "model": "jev08:latest",
        "answers": {name: {"type": "noul", "noul": score} for name, score in scores.items()},
        "usage": {"input_tokens": 123, "output_tokens": 0},
    }

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps(envelope).encode("utf-8")

    with patch.object(system1_classifier.urllib.request, "urlopen", return_value=FakeResponse()):
        prediction, raw, elapsed = system1_classifier.classify_with_system1(
            article_id=aid, title="Test article", abstract="abstract"
        )

    assert prediction.scores.digital_health_ai == 0.7
    assert prediction.labels.digital_health_ai is True
    assert prediction.labels.ai_relevant is False
    assert raw == envelope
    prediction_id = system1_classifier.persist_system1_prediction(
        article_id=aid, run_id="test-run", prediction=prediction,
        envelope=envelope, elapsed_ms=elapsed,
        input_hash="input-hash", model_name="jev08:latest",
    )
    saved = list_model_predictions(aid)
    current = get_current_classification(aid)
    assert saved[0]["id"] == prediction_id
    assert saved[0]["scores"]["digital_health_ai"] == 0.7
    assert current["review_status"] == "system1"
    assert current["adjustments"] == []
