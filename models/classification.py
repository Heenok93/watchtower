"""Pydantic contracts for Watchtower's article-level multilabel pipeline.

System 1 and System 2 predictions are stored as independent observations.
The eight model dimensions are deliberately flat: no primary/secondary
hierarchy is encoded in the persistence contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClassificationDimension(str, Enum):
    AI_RELEVANT = "ai_relevant"
    HEALTH_RELEVANT = "health_relevant"
    AGENTIC_AI_HEALTH = "agentic_ai_health"
    DIGITAL_HEALTH_AI = "digital_health_ai"
    CLINICAL_MEDICINE_AI = "clinical_medicine_ai"
    LABORATORY_AI = "laboratory_ai"
    EPIDEMICS_PUBLIC_HEALTH_AI = "epidemics_public_health_ai"
    DRUG_DEVELOPMENT_AI = "drug_development_ai"


CLASSIFICATION_DIMENSIONS: tuple[str, ...] = tuple(
    dimension.value for dimension in ClassificationDimension
)


class ClassificationScores(BaseModel):
    """Raw Noul/model scores, each constrained to [0, 1]."""

    model_config = ConfigDict(extra="forbid")

    ai_relevant: float = Field(ge=0.0, le=1.0)
    health_relevant: float = Field(ge=0.0, le=1.0)
    agentic_ai_health: float = Field(ge=0.0, le=1.0)
    digital_health_ai: float = Field(ge=0.0, le=1.0)
    clinical_medicine_ai: float = Field(ge=0.0, le=1.0)
    laboratory_ai: float = Field(ge=0.0, le=1.0)
    epidemics_public_health_ai: float = Field(ge=0.0, le=1.0)
    drug_development_ai: float = Field(ge=0.0, le=1.0)

    def as_dict(self) -> dict[str, float]:
        return self.model_dump(mode="json")


class ClassificationLabels(BaseModel):
    """Flat multilabel decisions corresponding to the eight score dimensions."""

    model_config = ConfigDict(extra="forbid")

    ai_relevant: bool
    health_relevant: bool
    agentic_ai_health: bool
    digital_health_ai: bool
    clinical_medicine_ai: bool
    laboratory_ai: bool
    epidemics_public_health_ai: bool
    drug_development_ai: bool

    def as_dict(self) -> dict[str, bool]:
        return self.model_dump(mode="json")


class ArticleClassificationPrediction(BaseModel):
    """A raw prediction from one model; no consistency repair is applied here."""

    model_config = ConfigDict(extra="forbid")

    scores: ClassificationScores
    labels: ClassificationLabels
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    rationales: dict[str, str] = Field(default_factory=dict)
    raw_response: str | dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_dimension_keys(self) -> "ArticleClassificationPrediction":
        allowed = set(CLASSIFICATION_DIMENSIONS)
        unknown_evidence = set(self.evidence) - allowed
        unknown_rationales = set(self.rationales) - allowed
        if unknown_evidence or unknown_rationales:
            raise ValueError(
                "Unknown classification dimensions: "
                f"evidence={sorted(unknown_evidence)}, "
                f"rationales={sorted(unknown_rationales)}"
            )
        return self


class ClassificationAdjustment(BaseModel):
    """An explicit consistency adjustment applied during consolidation."""

    dimension: ClassificationDimension
    previous_value: bool
    new_value: bool
    rule_id: str
    explanation: str


class ConsolidatedArticleClassification(BaseModel):
    """Current article-level multilabel result, preserving all eight scores."""

    model_config = ConfigDict(extra="forbid")

    article_id: int = Field(gt=0)
    scores: ClassificationScores
    labels: ClassificationLabels
    adjustments: list[ClassificationAdjustment] = Field(default_factory=list)
    taxonomy_version: str = "watchtower-v2"
    system1_prediction_id: int | None = None
    system2_prediction_id: int | None = None
    review_status: Literal["system1", "system2", "final", "needs_review", "stale"] = "system1"
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ModelPredictionRecord(BaseModel):
    """Metadata and raw output for an immutable model execution."""

    article_id: int = Field(gt=0)
    run_id: str
    model_role: Literal["system1", "system2", "other"]
    provider_name: str
    model_name: str
    model_version: str | None = None
    prompt_version: str
    prompt_hash: str
    taxonomy_version: str
    input_hash: str
    prediction: ArticleClassificationPrediction
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    status: Literal["completed", "failed", "interrupted", "invalid"] = "completed"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
