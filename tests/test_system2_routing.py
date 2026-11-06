from processing.system2_routing import CUTOFFS, route_scores
from models.classification import CLASSIFICATION_DIMENSIONS


def test_route_scores_routes_only_configured_uncertainty_bands():
    scores = {name: 0.1 for name in CLASSIFICATION_DIMENSIONS}
    scores.update({
        "ai_relevant": 0.7,
        "health_relevant": 0.8,
        "agentic_ai_health": 0.53,
        "digital_health_ai": 0.60,
        "clinical_medicine_ai": 0.7,
        "laboratory_ai": 0.7,
        "epidemics_public_health_ai": 0.8,
        "drug_development_ai": 0.83,
    })
    result = route_scores(scores)
    assert result["review_dimensions"] == [
        "agentic_ai_health", "digital_health_ai", "drug_development_ai"
    ]
    assert result["needs_system2"] is True
    assert result["labels"]["ai_relevant"] is True


def test_cutoff_boundaries_are_deterministic():
    scores = {name: 0.0 for name in CLASSIFICATION_DIMENSIONS}
    scores["digital_health_ai"] = CUTOFFS["digital_health_ai"]["low"]
    scores["drug_development_ai"] = CUTOFFS["drug_development_ai"]["high"]
    result = route_scores(scores)
    assert "digital_health_ai" in result["review_dimensions"]
    assert "drug_development_ai" not in result["review_dimensions"]
    assert result["labels"]["drug_development_ai"] is True
