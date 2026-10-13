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
            source_url
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            article.title,
            article.abstract,
            article.doi,
            article.pmid,
            article.source,
            article.source_url
        )
    )

    conn.commit()
    conn.close()