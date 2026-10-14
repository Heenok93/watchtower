import hashlib
import re
import unicodedata

from models.schemas import Article
from storage.repositories import (
    article_exists_by_doi,
    article_exists_by_pmid,
    article_exists_by_source_url,
    article_exists_by_fingerprint,
)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.lower().strip()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def build_article_fingerprint(
    article: Article,
) -> str | None:

    normalized_title = normalize_text(
        article.title
    )

    if not normalized_title:
        return None

    first_author = ""

    if article.authors:
        first_author = normalize_text(
            article.authors[0]
        )

    publication_date = ""

    if article.publication_date:
        publication_date = (
            article.publication_date.isoformat()
        )

    fingerprint_source = "|".join(
        [
            normalized_title,
            first_author,
            publication_date,
        ]
    )

    return hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()


def get_duplicate_reason(
    article: Article,
) -> str | None:

    if (
        article.doi
        and article_exists_by_doi(article.doi)
    ):
        return "doi"

    if (
        article.pmid
        and article_exists_by_pmid(article.pmid)
    ):
        return "pmid"

    if (
        article.source_url
        and article_exists_by_source_url(
            article.source_url
        )
    ):
        return "source_url"

    fingerprint = build_article_fingerprint(
        article
    )

    if (
        fingerprint
        and article_exists_by_fingerprint(
            fingerprint
        )
    ):
        return "fingerprint"

    return None