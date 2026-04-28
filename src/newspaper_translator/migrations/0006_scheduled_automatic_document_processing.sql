CREATE TABLE scheduler_runs (
    scheduler_run_id TEXT PRIMARY KEY,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    import_run_id TEXT,
    selected_document_count INTEGER NOT NULL DEFAULT 0,
    completed_document_count INTEGER NOT NULL DEFAULT 0,
    failed_document_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (import_run_id) REFERENCES import_runs (run_id)
);

CREATE TABLE document_processing_runs (
    processing_run_id TEXT PRIMARY KEY,
    scheduler_run_id TEXT,
    document_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL,
    automatic_failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_step TEXT,
    last_error_message TEXT,
    last_attempt_started_at TEXT,
    last_attempt_finished_at TEXT,
    locked_by TEXT,
    lock_expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scheduler_run_id) REFERENCES scheduler_runs (scheduler_run_id),
    FOREIGN KEY (document_key) REFERENCES documents (document_key)
);

CREATE INDEX idx_scheduler_runs_started_at
    ON scheduler_runs (started_at);
CREATE INDEX idx_document_processing_runs_status_updated_at
    ON document_processing_runs (status, updated_at);
CREATE INDEX idx_document_processing_runs_lock_expires_at
    ON document_processing_runs (lock_expires_at);
