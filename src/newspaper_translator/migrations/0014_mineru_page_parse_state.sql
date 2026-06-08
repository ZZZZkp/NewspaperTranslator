CREATE TABLE mineru_page_parse_state (
    document_key TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    batch_id TEXT,
    file_name TEXT,
    state TEXT NOT NULL,
    full_zip_url TEXT,
    markdown_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_key, page_number)
);

CREATE INDEX idx_mineru_page_parse_state_document_key
    ON mineru_page_parse_state (document_key);
