from copy import deepcopy

import requests

from enrichment.crossref_provider import (
    get_by_doi as crossref_get_by_doi,
    search_by_title as crossref_search_by_title,
)
from enrichment.openalex_provider import (
    get_by_doi as openalex_get_by_doi,
    search_by_title as openalex_search_by_title,
)
from models.schemas import Article
from processing.abstract_quality import (
    assess_abstract_quality,
)


def apply_enrichment(
    article: Article,
    result,
) -> Article:
    """
    Fill missing or poor metadata without destructively
    replacing good Watchtower data.
    """

    enriched = deepcopy(
        article
    )

    if not result.matched:
        return enriched

    current_quality = (
        assess_abstract_quality(
            abstract=enriched.abstract,
            title=enriched.title,
        )
    )

    if result.abstract:
        enriched_quality = (
            assess_abstract_quality(
                abstract=result.abstract,
                title=enriched.title,
            )
        )

        quality_rank = {
            "missing": 0,
            "metadata_only": 1,
            "short": 2,
            "usable": 3,
        }

        if (
            quality_rank[
                enriched_quality.quality
            ]
            >
            quality_rank[
                current_quality.quality
            ]
        ):
            enriched.abstract = (
                result.abstract
            )

    if (
        not enriched.authors
        and result.authors
    ):
        enriched.authors = (
            result.authors
        )

    if (
        enriched.publication_date
        is None
        and result.publication_date
        is not None
    ):
        enriched.publication_date = (
            result.publication_date
        )

    if (
        not enriched.doi
        and result.doi
    ):
        enriched.doi = result.doi

    if (
        not enriched.pmid
        and result.pmid
    ):
        enriched.pmid = result.pmid

    if (
        not enriched.journal
        and result.journal
    ):
        enriched.journal = (
            result.journal
        )

    return enriched


def enrich_article(
    article: Article,
) -> tuple[Article, list]:
    """
    Lightweight enrichment cascade.

    DOI:
        OpenAlex -> Crossref

    No DOI:
        OpenAlex title search -> Crossref title search

    Each successful result may complement the previous one.
    """

    enriched = deepcopy(
        article
    )

    results = []

    if article.doi:
        providers = [
            (
                "openalex",
                openalex_get_by_doi,
            ),
            (
                "crossref",
                crossref_get_by_doi,
            ),
        ]

        lookup_value = article.doi

    else:
        providers = [
            (
                "openalex",
                openalex_search_by_title,
            ),
            (
                "crossref",
                crossref_search_by_title,
            ),
        ]

        lookup_value = article.title

    for provider_name, provider_call in providers:
        try:
            result = provider_call(
                lookup_value
            )

        except requests.RequestException as exc:
            print(
                f"Enrichment warning "
                f"({provider_name}): {exc}"
            )

            continue

        results.append(
            result
        )

        if result.matched:
            enriched = apply_enrichment(
                article=enriched,
                result=result,
            )

        quality = assess_abstract_quality(
            abstract=enriched.abstract,
            title=enriched.title,
        )

        if (
            quality.quality
            == "usable"
            and enriched.doi
            and enriched.authors
            and enriched.publication_date
        ):
            break

    return (
        enriched,
        results,
    )