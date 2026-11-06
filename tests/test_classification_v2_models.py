from pydantic import ValidationError
import pytest

from models.classification import (
    CLASSIFICATION_DIMENSIONS,
    ArticleClassificationPrediction,
    ClassificationLabels,
    ClassificationScores,
)


def test_v2_has_eight_flat_dimensions():
    assert len(CLASSIFICATION_DIMENSIONS) == 8
    assert "drug_development_ai" in CLASSIFICATION_DIMENSIONS
    assert "non_agentic_ai_health" not in CLASSIFICATION_DIMENSIONS


def test_scores_are_bounded_and_complete():
    values = {name: 0.5 for name in CLASSIFICATION_DIMENSIONS}
    scores = ClassificationScores(**values)
    assert scores.ai_relevant == 0.5
    with pytest.raises(ValidationError):
        ClassificationScores(**{**values, "drug_development_ai": 1.2})


def test_raw_prediction_does_not_enforce_cross_label_repairs():
    values = {name: False for name in CLASSIFICATION_DIMENSIONS}
    labels = ClassificationLabels(**{**values, "drug_development_ai": True})
    scores = ClassificationScores(**{name: 0.8 for name in CLASSIFICATION_DIMENSIONS})
    prediction = ArticleClassificationPrediction(scores=scores, labels=labels)
    # Raw predictions remain untouched; consistency rules belong to consolidation.
    assert prediction.labels.drug_development_ai is True
    assert prediction.labels.ai_relevant is False
