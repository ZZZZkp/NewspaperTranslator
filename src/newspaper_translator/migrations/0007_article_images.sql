CREATE TABLE article_images (
    article_image_id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    image_path TEXT NOT NULL,
    image_order INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_id) REFERENCES final_articles (article_id)
);

CREATE INDEX idx_article_images_article_id_image_order
    ON article_images (article_id, image_order);
