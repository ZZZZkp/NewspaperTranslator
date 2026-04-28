CREATE TABLE parse_runs (
    parse_run_id TEXT PRIMARY KEY,
    document_key TEXT NOT NULL,
    status TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    continuation_matcher_name TEXT NOT NULL DEFAULT '',
    continuation_matcher_version TEXT NOT NULL DEFAULT '',
    mineru_batch_id TEXT,
    mineru_file_id TEXT,
    markdown_path TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    error_message TEXT,
    FOREIGN KEY (document_key) REFERENCES documents (document_key)
);

CREATE TABLE article_fragments (
    fragment_id TEXT PRIMARY KEY,
    parse_run_id TEXT NOT NULL,
    source_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    body_text TEXT NOT NULL,
    continued_to_page TEXT NOT NULL DEFAULT '',
    continued_from_page TEXT NOT NULL DEFAULT '',
    is_continuation_candidate INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parse_run_id) REFERENCES parse_runs (parse_run_id)
);

CREATE TABLE continuation_matches (
    match_id TEXT PRIMARY KEY,
    parse_run_id TEXT NOT NULL,
    front_fragment_id TEXT,
    back_fragment_id TEXT,
    matcher_name TEXT NOT NULL,
    matcher_raw_response TEXT NOT NULL,
    decision_status TEXT NOT NULL,
    decision_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parse_run_id) REFERENCES parse_runs (parse_run_id),
    FOREIGN KEY (front_fragment_id) REFERENCES article_fragments (fragment_id),
    FOREIGN KEY (back_fragment_id) REFERENCES article_fragments (fragment_id)
);

CREATE TABLE final_articles (
    article_id TEXT PRIMARY KEY,
    parse_run_id TEXT NOT NULL,
    document_key TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    article_order INTEGER NOT NULL,
    primary_source_order INTEGER NOT NULL,
    source_fragment_count INTEGER NOT NULL,
    title_en TEXT NOT NULL,
    body_text_en TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parse_run_id) REFERENCES parse_runs (parse_run_id),
    FOREIGN KEY (document_key) REFERENCES documents (document_key)
);

CREATE TABLE final_article_fragments (
    article_id TEXT NOT NULL,
    fragment_id TEXT NOT NULL,
    fragment_role TEXT NOT NULL,
    sequence_index INTEGER NOT NULL,
    PRIMARY KEY (article_id, fragment_id),
    FOREIGN KEY (article_id) REFERENCES final_articles (article_id),
    FOREIGN KEY (fragment_id) REFERENCES article_fragments (fragment_id)
);

CREATE TABLE article_enrichment_runs (
    enrichment_run_id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    parse_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    error_message TEXT,
    FOREIGN KEY (article_id) REFERENCES final_articles (article_id),
    FOREIGN KEY (parse_run_id) REFERENCES parse_runs (parse_run_id)
);

CREATE TABLE article_enrichment_outputs (
    enrichment_run_id TEXT PRIMARY KEY,
    translated_title_zh TEXT,
    summary_zh TEXT,
    translated_body_zh TEXT,
    translation_status TEXT NOT NULL,
    summary_status TEXT NOT NULL,
    tagging_status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (enrichment_run_id) REFERENCES article_enrichment_runs (enrichment_run_id)
);

CREATE TABLE article_tags (
    article_tag_id TEXT PRIMARY KEY,
    enrichment_run_id TEXT NOT NULL,
    tag_text TEXT NOT NULL,
    tag_order INTEGER NOT NULL,
    FOREIGN KEY (enrichment_run_id) REFERENCES article_enrichment_runs (enrichment_run_id)
);

CREATE INDEX idx_parse_runs_document_key_status_finished_at
    ON parse_runs (document_key, status, finished_at);
CREATE INDEX idx_article_fragments_parse_run_id_source_order
    ON article_fragments (parse_run_id, source_order);
CREATE INDEX idx_continuation_matches_parse_run_id_decision_status
    ON continuation_matches (parse_run_id, decision_status);
CREATE INDEX idx_final_articles_parse_run_id_article_order
    ON final_articles (parse_run_id, article_order);
CREATE INDEX idx_final_articles_publication_date_article_order
    ON final_articles (publication_date, article_order);
CREATE INDEX idx_article_enrichment_runs_article_id_status_finished_at
    ON article_enrichment_runs (article_id, status, finished_at);
CREATE INDEX idx_article_tags_enrichment_run_id_tag_order
    ON article_tags (enrichment_run_id, tag_order);
CREATE INDEX idx_article_tags_tag_text
    ON article_tags (tag_text);
