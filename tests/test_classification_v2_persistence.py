from pathlib import Path

from models.classification import (
    CLASSIFICATION_DIMENSIONS,
    ArticleClassificationPrediction,
    ClassificationLabels,
    ClassificationScores,
    ConsolidatedArticleClassification,
    ModelPredictionRecord,
)
import storage.database as database
from storage.classification_repository import (
    get_current_classification,
    list_model_predictions,
    save_consolidated_classification,
    save_model_prediction,
)


def test_migrations_and_prediction_history_are_additive(tmp_path, monkeypatch):
    test_db = tmp_path / "watchtower_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db)

    # Build a fresh schema: production SQLite data is intentionally not shipped.
    database.init_database()
    with database.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO articles (title, source, collected_at) VALUES (?, ?, ?)",
            ("Test article", "pytest", "2026-11-06T00:00:00Z"),
        )
        article_id = cursor.lastrowid

    database.init_database()  # Migration runner is idempotent.

    with database.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=8").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] > 0

    scores = ClassificationScores(**{name: 0.4 for name in CLASSIFICATION_DIMENSIONS})
    labels = ClassificationLabels(**{name: False for name in CLASSIFICATION_DIMENSIONS})
    prediction = ArticleClassificationPrediction(scores=scores, labels=labels)
    record = ModelPredictionRecord(
        article_id=article_id,
        run_id="test-run",
        model_role="system1",
        provider_name="systemone",
        model_name="jev-0.8",
        prompt_version="v3",
        prompt_hash="prompt-hash",
        taxonomy_version="watchtower-v2",
        input_hash="input-hash",
        prediction=prediction,
    )
    prediction_id = save_model_prediction(record)

    first = ConsolidatedArticleClassification(
        article_id=article_id,
        scores=scores,
        labels=labels,
        system1_prediction_id=prediction_id,
    )
    assert save_consolidated_classification(first) == 1
    assert save_consolidated_classification(first.model_copy(update={"review_status": "final"})) == 2

    current = get_current_classification(article_id)
    assert current["revision"] == 2
    assert current["review_status"] == "final"
    assert len(list_model_predictions(article_id)) == 1
