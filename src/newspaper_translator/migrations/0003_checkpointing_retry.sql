ALTER TABLE import_runs ADD COLUMN checkpoint_before TEXT;
ALTER TABLE import_runs ADD COLUMN checkpoint_after TEXT;

ALTER TABLE import_run_items ADD COLUMN message_internal_date TEXT;

CREATE TABLE import_checkpoints (
    source_name TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,
    checkpoint_value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_name, checkpoint_type)
);

CREATE TABLE failed_messages (
    message_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    message_internal_date TEXT NOT NULL,
    retry_state TEXT NOT NULL,
    retry_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_run_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_failed_messages_retry_state ON failed_messages (retry_state);
