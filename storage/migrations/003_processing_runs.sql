CREATE TABLE IF NOT EXISTS processing_runs (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    run_type TEXT NOT NULL,

    started_at TIMESTAMP,

    finished_at TIMESTAMP,

    status TEXT,

    records_processed INTEGER,

    error_message TEXT
);