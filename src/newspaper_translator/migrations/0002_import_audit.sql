CREATE TABLE import_runs (
    run_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL,
    query TEXT NOT NULL,
    allowed_senders_json TEXT NOT NULL,
    max_results INTEGER NOT NULL,
    fetched_message_count INTEGER NOT NULL DEFAULT 0,
    imported_attachment_count INTEGER NOT NULL DEFAULT 0,
    created_document_count INTEGER NOT NULL DEFAULT 0,
    skipped_document_count INTEGER NOT NULL DEFAULT 0,
    failed_item_count INTEGER NOT NULL DEFAULT 0,
    skipped_item_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE import_run_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_key TEXT NOT NULL,
    message_id TEXT,
    attachment_id TEXT,
    link_url TEXT,
    status TEXT NOT NULL,
    detail_code TEXT NOT NULL,
    detail_message TEXT NOT NULL,
    document_key TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES import_runs (run_id)
);

CREATE INDEX idx_import_run_items_run_id ON import_run_items (run_id);
CREATE INDEX idx_import_run_items_status ON import_run_items (status);
