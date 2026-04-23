CREATE TABLE documents (
    document_key TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_attachment_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    import_status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE processing_tasks (
    task_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
