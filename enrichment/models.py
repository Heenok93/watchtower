from datetime import date

from pydantic import BaseModel, Field


class EnrichmentResult(BaseModel):
    provider: str

    matched: bool = False
    match_method: str | None = None

    title: str | None = None
    abstract: str | None = None

    authors: list[str] = Field(
        default_factory=list
    )

    publication_date: date | None = None

    doi: str | None = None
    pmid: str | None = None

    journal: str | None = None

    external_id: str | None = None
