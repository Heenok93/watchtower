import re
from datetime import date
from difflib import SequenceMatcher
from urllib.parse import quote

import requests

from enrichment.models import EnrichmentResult


BASE_URL = "https://api.crossref.org"


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


def strip_jats(
    text: str | None,
) -> str | None:
    """
    Crossref abstracts may contain markup.
    Keep cleaning deliberately lightweight.
    """

    if not text:
        return None

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = " ".join(
        text.split()
    )

    return text or None


def extract_first(
    data,
    key,
) -> str | None:
    value = data.get(
        key
    )

    if (
        isinstance(value, list)
        and value
    ):
        return value[0]

    return None

def extract_authors(
    item,
) -> list[str]:
    authors = []

    for author in item.get(
        "author",
        [],
    ):
        given = author.get(
            "given",
            "",
        ).strip()

        family = author.get(
            "family",
            "",
        ).strip()

        name = " ".join(
            part
            for part in [
                given,
                family,
            ]
            if part
        )

        if name:
            authors.append(name)

    return authors

def extract_date(
    item,
) -> date | None:

    for key in [
        "published-online",
        "published-print",
        "published",
        "issued",
    ]:
        value = item.get(
            key
        ) or {}

        parts = value.get(
            "date-parts"
        )

        if not parts:
            continue

        values = parts[0]

        if not values:
            continue

        year = values[0]

        month = (
            values[1]
            if len(values) > 1
            else 1
        )

        day = (
            values[2]
            if len(values) > 2
            else 1
        )

        try:
            return date(
                year,
                month,
                day,
            )
        except ValueError:
            continue

    return None


def item_to_result(
    item,
    match_method,
) -> EnrichmentResult:

    return EnrichmentResult(
        provider="crossref",
        matched=True,
        match_method=match_method,
        title=extract_first(
            item,
            "title",
        ),
        abstract=strip_jats(
            item.get(
                "abstract"
            )
        ),
        authors=extract_authors(
            item
        ),
        publication_date=(
            extract_date(item)
        ),
        doi=item.get("DOI"),
        journal=extract_first(
            item,
            "container-title",
        ),
        external_id=item.get("URL"),
    )


def get_by_doi(
    doi: str,
) -> EnrichmentResult:

    response = requests.get(
        (
            f"{BASE_URL}/works/"
            f"{quote(doi, safe='')}"
        ),
        timeout=20,
    )

    if response.status_code == 404:
        return EnrichmentResult(
            provider="crossref"
        )

    response.raise_for_status()

    item = response.json()[
        "message"
    ]

    return item_to_result(
        item,
        match_method="doi",
    )


def search_by_title(
    title: str,
    similarity_threshold: float = 0.92,
) -> EnrichmentResult:

    response = requests.get(
        f"{BASE_URL}/works",
        params={
            "query.bibliographic": title,
            "rows": 5,
        },
        timeout=20,
    )

    response.raise_for_status()

    items = (
        response.json()
        .get("message", {})
        .get("items", [])
    )

    if not items:
        return EnrichmentResult(
            provider="crossref"
        )

    best_item = None
    best_similarity = 0.0

    for item in items:
        candidate_title = extract_first(
            item,
            "title",
        )

        similarity = title_similarity(
            title,
            candidate_title,
        )

        if similarity > best_similarity:
            best_similarity = similarity
            best_item = item

    if (
        best_item is None
        or best_similarity
        < similarity_threshold
    ):
        return EnrichmentResult(
            provider="crossref"
        )

    return item_to_result(
        best_item,
        match_method="title",
    )