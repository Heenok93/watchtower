CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT,

    publication_date TEXT,

    doi TEXT,
    pmid TEXT,

    source TEXT NOT NULL,
    source_url TEXT,
    journal TEXT,

    collected_at TEXT NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_doi
ON articles(doi)
WHERE doi IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_pmid
ON articles(pmid)
WHERE pmid IS NOT NULL;