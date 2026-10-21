from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMResult(BaseModel):
    """
    Validated output returned by an LLM for an article/topic pair.

    This model contains only the scientific classification produced
    by the LLM. Technical metadata such as the model name, provider,
    article ID, topic ID, and processing timestamp are stored
    separately by Watchtower.
    """

    model_config = ConfigDict(extra="forbid")

    relevant: bool

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    reason: str = Field(
        min_length=1,
        max_length=1000,
    )

    summary: str = Field(
        min_length=1,
        max_length=1500,
    )