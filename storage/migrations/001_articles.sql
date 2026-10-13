CREATE TABLE IF NOT EXISTS articles (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    title TEXT NOT NULL,

    abstract TEXT,

    doi TEXT,
    pmid TEXT,

    source TEXT NOT NULL,
    source_url TEXT,

    publication_date TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_articles_doi
ON articles(doi);

CREATE INDEX IF NOT EXISTS idx_articles_pmid
ON articles(pmid);