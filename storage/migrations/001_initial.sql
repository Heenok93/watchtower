CREATE TABLE IF NOT EXISTS articles (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    title TEXT NOT NULL,

    abstract TEXT,

    doi TEXT,
    pmid TEXT,

    source TEXT,
    source_url TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);