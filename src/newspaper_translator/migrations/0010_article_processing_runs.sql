CREATE TABLE article_processing_runs (
    article_processing_run_id TEXT PRIMARY KEY,
    article_key TEXT NOT NULL UNIQUE,
    article_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL,
    automatic_failure_count INTEGER NOT NULL DEFAULT 0,
    last_error_message TEXT,
    last_success_input_hash TEXT,
    last_attempt_started_at TEXT,
    last_attempt_finished_at TEXT,
    locked_by TEXT,
    lock_expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES final_articles (article_id)
);

CREATE INDEX idx_article_processing_runs_status_updated_at
    ON article_processing_runs (status, updated_at);
