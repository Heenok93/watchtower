from storage.database import get_connection


conn = get_connection()

cur = conn.cursor()

cur.execute(
    """
    CREATE TABLE IF NOT EXISTS articles (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        title TEXT NOT NULL,

        abstract TEXT,

        doi TEXT,

        pmid TEXT,

        source TEXT,

        source_url TEXT,

        publication_date TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
)

cur.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_articles_doi
    ON articles(doi)
    """
)

conn.commit()

conn.close()

print("Database initialized.")