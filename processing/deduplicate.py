import hashlib
import re
import unicodedata

from models.schemas import Article
from processing.normalize import normalize_doi, normalize_pmid
from storage.repositories import (
    article_exists_by_doi,
    article_exists_by_pmid,
    article_exists_by_source_url,
    article_exists_by_fingerprint,
)


def normalize_text(text: str | None) -> str:
    """Normalize bibliographic text for stable exact comparisons."""
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text if not unicodedata.combining(char)
    )
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_article_fingerprint(article: Article) -> str | None:
    """Build an exact-match fingerprint from normalized title, author and date.

    The publication date is intentionally retained to reduce false-positive
    merges between distinct records with generic or reused titles.
    """
    normalized_title = normalize_text(article.title)
    if not normalized_title:
        return None

    first_author = normalize_text(article.authors[0]) if article.authors else ""
    publication_date = (
        article.publication_date.isoformat()
        if article.publication_date
        else ""
    )

    fingerprint_source = "|".join(
        [normalized_title, first_author, publication_date]
    )
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()


def get_duplicate_reason(article: Article) -> str | None:
    """Return the strongest matching duplicate criterion, if any."""
    doi = normalize_doi(article.doi)
    if doi and article_exists_by_doi(doi):
        return "doi"

    pmid = normalize_pmid(article.pmid)
    if pmid and article_exists_by_pmid(pmid):
        return "pmid"

    if article.source_url and article_exists_by_source_url(article.source_url):
        return "source_url"

    fingerprint = build_article_fingerprint(article)
    if fingerprint and article_exists_by_fingerprint(fingerprint):
        return "fingerprint"

    return None
