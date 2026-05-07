ALTER TABLE documents ADD COLUMN source_message_internal_date TEXT;

CREATE INDEX idx_documents_content_hash
    ON documents (content_hash);
