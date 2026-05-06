ALTER TABLE article_enrichment_outputs
    ADD COLUMN content_type TEXT NOT NULL DEFAULT 'article';

ALTER TABLE article_enrichment_outputs
    ADD COLUMN classification_reason TEXT NOT NULL DEFAULT '';
