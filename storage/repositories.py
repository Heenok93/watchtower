from storage.database import get_connection


def save_article(article):

    conn = get_connection()

    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO articles (
            title,
            abstract,
            doi,
            pmid,
            source,
            source_url,
            publication_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article.title,
            article.abstract,
            article.doi,
            article.pmid,
            article.source,
            article.source_url,
            article.publication_date
        )
    )

    conn.commit()
    conn.close()


def article_exists_by_doi(doi: str) -> bool:

    conn = get_connection()

    cur = conn.cursor()

    cur.execute(
        """
        SELECT id
        FROM articles
        WHERE doi = ?
        LIMIT 1
        """,
        (doi,)
    )

    row = cur.fetchone()

    conn.close()

    return row is not None


def count_articles():

    conn = get_connection()

    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM articles
        """
    )

    result = cur.fetchone()[0]

    conn.close()

    return result