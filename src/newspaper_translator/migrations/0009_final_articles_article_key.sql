ALTER TABLE final_articles
    ADD COLUMN article_key TEXT NOT NULL DEFAULT '';

UPDATE final_articles
SET article_key = article_id
WHERE article_key = '';

CREATE INDEX idx_final_articles_document_key_article_key
    ON final_articles (document_key, article_key);
