"""Production routing cutoffs for System 2 review (calibration v1)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.classification import CLASSIFICATION_DIMENSIONS

CALIBRATION_VERSION = "jev08_cutoffs_operational_v1_2026-11-06"
SCENARIO = "high_recall_15pct"

# For equal cutoffs, the dimension is decided automatically by System 1.
# For a band, [low, high) is routed to System 2; >= high is positive.
CUTOFFS: dict[str, dict[str, float]] = {
    "ai_relevant": {"low": 0.422, "high": 0.422},
    "health_relevant": {"low": 0.543, "high": 0.543},
    "agentic_ai_health": {"low": 0.500, "high": 0.560},
    "digital_health_ai": {"low": 0.540, "high": 0.665},
    "clinical_medicine_ai": {"low": 0.402, "high": 0.402},
    "laboratory_ai": {"low": 0.489, "high": 0.489},
    "epidemics_public_health_ai": {"low": 0.732, "high": 0.732},
    "drug_development_ai": {"low": 0.800, "high": 0.860},
}

if set(CUTOFFS) != set(CLASSIFICATION_DIMENSIONS):
    raise RuntimeError("System 2 routing cutoffs do not cover the frozen taxonomy.")

for _dimension, _cutoff in CUTOFFS.items():
    if not (0 <= _cutoff["low"] <= _cutoff["high"] <= 1):
        raise RuntimeError(f"Invalid cutoff range for {_dimension}: {_cutoff}")


def route_scores(scores: dict[str, Any]) -> dict[str, Any]:
    """Return final System1 decisions and the dimensions requiring System2."""
    missing = set(CLASSIFICATION_DIMENSIONS) - set(scores)
    if missing:
        raise ValueError(f"Missing System1 scores: {sorted(missing)}")

    labels: dict[str, bool] = {}
    review_dimensions: list[str] = []
    for dimension in CLASSIFICATION_DIMENSIONS:
        score = float(scores[dimension])
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"Invalid score for {dimension}: {score}")
        low, high = CUTOFFS[dimension]["low"], CUTOFFS[dimension]["high"]
        if low < high and low <= score < high:
            review_dimensions.append(dimension)
            # Provisional value is deliberately not treated as final downstream.
            labels[dimension] = score >= (low + high) / 2
        else:
            labels[dimension] = score >= high
    return {
        "labels": labels,
        "review_dimensions": review_dimensions,
        "needs_system2": bool(review_dimensions),
        "calibration_version": CALIBRATION_VERSION,
        "scenario": SCENARIO,
    }
