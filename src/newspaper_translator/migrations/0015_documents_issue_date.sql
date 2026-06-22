ALTER TABLE documents ADD COLUMN issue_date TEXT;

CREATE INDEX idx_documents_source_name_issue_date
    ON documents (source_name, issue_date);
