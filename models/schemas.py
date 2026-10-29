from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class Article(BaseModel):
    title: str

    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)

    publication_date: date | None = None

    doi: str | None = None
    pmid: str | None = None

    source: str
    source_url: str | None = None
    journal: str | None = None

    content_type: str = "unknown"

    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class TopicTerms(BaseModel):
    any: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)


class PriorityTerms(BaseModel):
    high: list[str] = Field(default_factory=list)


class RequiredGroup(BaseModel):
    terms: list[str] = Field(default_factory=list)


class ScoringConfig(BaseModel):
    include_match: int = 2
    context_match: int = 2
    priority_match: int = 3
    exclude_match: int = -10


class ThresholdConfig(BaseModel):
    reject_below: int = 2
    llm_review_below: int = 6


class TopicProfile(BaseModel):
    id: str
    name: str
    description: str

    include: TopicTerms = Field(
        default_factory=TopicTerms
    )

    exclude: TopicTerms = Field(
        default_factory=TopicTerms
    )

    priority: PriorityTerms = Field(
        default_factory=PriorityTerms
    )

    required_groups: dict[str, RequiredGroup] = Field(
        default_factory=dict
    )

    secondary_groups: dict[str, RequiredGroup] = Field(
        default_factory=dict
    )

    scoring: ScoringConfig = Field(
        default_factory=ScoringConfig
    )

    thresholds: ThresholdConfig = Field(
        default_factory=ThresholdConfig
    )

    # Optional profile-local safeguards; defaults preserve existing profiles.
    strip_editorial_prefixes: bool = False
    min_candidate_score_for_candidate: int | None = None
    low_score_candidate_decision: Literal["reject", "llm_review"] = "reject"


class FilterResult(BaseModel):
    topic_id: str

    score: int

    decision: Literal[
        "reject",
        "llm_review",
        "candidate",
    ]

    matched_include: list[str] = Field(
        default_factory=list
    )

    matched_context: list[str] = Field(
        default_factory=list
    )

    matched_priority: list[str] = Field(
        default_factory=list
    )

    matched_exclude: list[str] = Field(
        default_factory=list
    )

    matched_required_groups: dict[str, list[str]] = Field(
        default_factory=dict
    )

    required_groups_satisfied: bool = False