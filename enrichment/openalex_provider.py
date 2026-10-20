from datetime import date
from difflib import SequenceMatcher

import requests

from enrichment.models import EnrichmentResult


BASE_URL = "https://api.openalex.org"


def normalize_doi(
    doi: str | None,
) -> str | None:
    """
    Normalize a DOI for OpenAlex lookup.
    """

    if not doi:
        return None

    doi = doi.strip()

    prefixes = [
        "https://doi.org/",
        "http://doi.org/",
        "doi:",
    ]

    doi_lower = doi.lower()

    for prefix in prefixes:
        if doi_lower.startswith(prefix):
            doi = doi[
                len(prefix):
            ]
            break

    doi = doi.strip()

    return doi or None


def normalize_title(
    title: str | None,
) -> str:
    if not title:
        return ""

    return " ".join(
        title.lower().strip().split()
    )


def title_similarity(
    title_a: str | None,
    title_b: str | None,
) -> float:
    return SequenceMatcher(
        None,
        normalize_title(title_a),
        normalize_title(title_b),
    ).ratio()


def reconstruct_abstract(
    inverted_index,
) -> str | None:
    """
    Reconstruct an abstract from OpenAlex's
    abstract_inverted_index.
    """

    if not inverted_index:
        return None

    positions = []

    for word, word_positions in (
        inverted_index.items()
    ):
        for position in word_positions:
            positions.append(
                (
                    position,
                    word,
                )
            )

    if not positions:
        return None

    positions.sort(
        key=lambda item: item[0]
    )

    return " ".join(
        word
        for _, word in positions
    )


def parse_date(
    value: str | None,
) -> date | None:
    if not value:
        return None

    try:
        return date.fromisoformat(
            value
        )

    except ValueError:
        return None


def extract_authors(
    work,
) -> list[str]:
    authors = []

    for authorship in work.get(
        "authorships",
        [],
    ):
        author = authorship.get(
            "author",
            {},
        )

        name = author.get(
            "display_name"
        )

        if name:
            authors.append(
                name
            )

    return authors


def extract_journal(
    work,
) -> str | None:
    primary_location = work.get(
        "primary_location"
    ) or {}

    source = primary_location.get(
        "source"
    ) or {}

    return source.get(
        "display_name"
    )


def extract_pmid(
    work,
) -> str | None:
    ids = work.get(
        "ids"
    ) or {}

    pmid = ids.get(
        "pmid"
    )

    if not pmid:
        return None

    return pmid.rsplit(
        "/",
        1,
    )[-1]


def extract_doi(
    work,
) -> str | None:
    doi = work.get(
        "doi"
    )

    return normalize_doi(
        doi
    )


def work_to_result(
    work,
    match_method,
) -> EnrichmentResult:

    return EnrichmentResult(
        provider="openalex",
        matched=True,
        match_method=match_method,
        title=work.get(
            "title"
        ),
        abstract=reconstruct_abstract(
            work.get(
                "abstract_inverted_index"
            )
        ),
        authors=extract_authors(
            work
        ),
        publication_date=parse_date(
            work.get(
                "publication_date"
            )
        ),
        doi=extract_doi(
            work
        ),
        pmid=extract_pmid(
            work
        ),
        journal=extract_journal(
            work
        ),
        external_id=work.get(
            "id"
        ),
    )


def get_by_doi(
    doi: str,
) -> EnrichmentResult:
    """
    Retrieve one OpenAlex Work directly by DOI.

    OpenAlex supports the short external-ID form:

        /works/doi:10.xxxx/...
    """

    normalized_doi = normalize_doi(
        doi
    )

    if not normalized_doi:
        return EnrichmentResult(
            provider="openalex"
        )

    response = requests.get(
        f"{BASE_URL}/works/doi:{normalized_doi}",
        timeout=20,
    )

    if response.status_code == 404:
        return EnrichmentResult(
            provider="openalex"
        )

    response.raise_for_status()

    return work_to_result(
        response.json(),
        match_method="doi",
    )


def search_by_title(
    title: str,
    similarity_threshold: float = 0.92,
) -> EnrichmentResult:
    """
    Search OpenAlex by title and accept only a
    high-similarity match.
    """

    if not title:
        return EnrichmentResult(
            provider="openalex"
        )

    response = requests.get(
        f"{BASE_URL}/works",
        params={
            "search.title": title,
            "per_page": 5,
        },
        timeout=20,
    )

    response.raise_for_status()

    results = response.json().get(
        "results",
        [],
    )

    if not results:
        return EnrichmentResult(
            provider="openalex"
        )

    best_work = None
    best_similarity = 0.0

    for work in results:
        similarity = title_similarity(
            title,
            work.get(
                "title"
            ),
        )

        if (
            similarity
            > best_similarity
        ):
            best_similarity = (
                similarity
            )

            best_work = work

    if (
        best_work is None
        or best_similarity
        < similarity_threshold
    ):
        return EnrichmentResult(
            provider="openalex"
        )

    return work_to_result(
        best_work,
        match_method="title",
    )