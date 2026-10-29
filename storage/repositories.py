import json

from models.schemas import Article
from processing.normalize import normalize_doi, normalize_pmid
from storage.database import get_connection


def article_exists_by_doi(
    doi: str | None,
) -> bool:

    if not doi:
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM articles
            WHERE doi = ?
            LIMIT 1
            """,
            (doi,),
        ).fetchone()

    return row is not None


def article_exists_by_pmid(
    pmid: str | None,
) -> bool:

    if not pmid:
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM articles
            WHERE pmid = ?
            LIMIT 1
            """,
            (pmid,),
        ).fetchone()

    return row is not None


def article_exists_by_source_url(
    source_url: str | None,
) -> bool:

    if not source_url:
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM articles
            WHERE source_url = ?
            LIMIT 1
            """,
            (source_url,),
        ).fetchone()

    return row is not None


def article_exists_by_fingerprint(
    fingerprint: str | None,
) -> bool:

    if not fingerprint:
        return False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM articles
            WHERE fingerprint = ?
            LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()

    return row is not None


def save_article(
    article: Article,
    fingerprint: str | None = None,
) -> int:

    article.doi = normalize_doi(article.doi)
    article.pmid = normalize_pmid(article.pmid)

    publication_date = (
        article.publication_date.isoformat()
        if article.publication_date
        else None
    )

    collected_at = (
        article.collected_at.isoformat()
    )

    authors_json = json.dumps(
        article.authors,
        ensure_ascii=False,
    )

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO articles (
                title,
                abstract,
                authors,
                publication_date,
                doi,
                pmid,
                source,
                source_url,
                journal,
                content_type,
                collected_at,
                fingerprint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.title,
                article.abstract,
                authors_json,
                publication_date,
                article.doi,
                article.pmid,
                article.source,
                article.source_url,
                article.journal,
                article.content_type,
                collected_at,
                fingerprint,
            ),
        )

        conn.commit()

        return cursor.lastrowid


def count_articles() -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM articles
            """
        ).fetchone()

    return row["count"]