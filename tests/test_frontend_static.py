import pathlib
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


class FrontendStaticTests(unittest.TestCase):
    def test_frontend_includes_dashboard_entry_files(self) -> None:
        frontend_root = PROJECT_ROOT / "frontend"
        index_path = frontend_root / "index.html"
        styles_path = frontend_root / "styles.css"
        app_path = frontend_root / "app.js"

        self.assertTrue(index_path.exists(), "frontend/index.html should exist")
        self.assertTrue(styles_path.exists(), "frontend/styles.css should exist")
        self.assertTrue(app_path.exists(), "frontend/app.js should exist")

    def test_frontend_index_defines_dashboard_sections(self) -> None:
        index_path = PROJECT_ROOT / "frontend" / "index.html"
        self.assertTrue(index_path.exists(), "frontend/index.html should exist")

        index_text = index_path.read_text()

        self.assertIn('id="primary-nav"', index_text)
        self.assertIn('id="summary-bar"', index_text)
        self.assertIn('id="filter-form"', index_text)
        self.assertIn('id="focus-tag-section"', index_text)
        self.assertIn('id="all-articles-section"', index_text)
        self.assertIn('id="article-detail-view"', index_text)
        self.assertIn('id="detail-image-gallery"', index_text)
        self.assertIn('id="detail-open-document-button"', index_text)
        self.assertIn('id="document-processing-section"', index_text)
        self.assertIn('id="workbench-action-row"', index_text)
        self.assertIn('id="manual-gmail-import-button"', index_text)
        self.assertIn('id="manual-gmail-import-status"', index_text)
        self.assertIn('id="document-detail-view"', index_text)
        self.assertIn('id="workbench-tabs"', index_text)
        self.assertIn('id="workbench-tab-documents"', index_text)
        self.assertIn('id="workbench-tab-articles"', index_text)
        self.assertIn('id="article-processing-section"', index_text)
        self.assertIn('id="article-processing-meta"', index_text)
        self.assertIn('id="article-processing-cards"', index_text)
        self.assertIn('id="article-processing-filter-form"', index_text)
        self.assertIn('id="article-processing-status-filter"', index_text)
        self.assertIn('id="article-processing-source-filter"', index_text)
        self.assertIn('id="article-processing-date-from-filter"', index_text)
        self.assertIn('id="article-processing-date-to-filter"', index_text)
        self.assertIn('id="article-processing-reset-filters"', index_text)
        self.assertIn('id="article-processing-detail-view"', index_text)
        self.assertIn('id="article-processing-detail-title"', index_text)
        self.assertIn('id="article-processing-detail-meta"', index_text)
        self.assertIn('id="article-processing-detail-error-summary"', index_text)
        self.assertIn('id="article-processing-detail-badges"', index_text)
        self.assertIn('id="article-processing-detail-fields"', index_text)
        self.assertIn('id="article-processing-identity-fields"', index_text)
        self.assertIn('id="article-processing-open-document-button"', index_text)
        self.assertIn('id="article-processing-open-article-button"', index_text)
        self.assertIn('id="article-processing-retry-button"', index_text)
        self.assertIn('id="article-processing-back-button"', index_text)
        self.assertIn('id="document-visible-articles"', index_text)
        self.assertIn('id="document-identity-fields"', index_text)
        self.assertIn('id="document-error-summary"', index_text)
        self.assertIn('src="./app.js"', index_text)

    def test_frontend_app_requests_dashboard_api_surfaces(self) -> None:
        app_path = PROJECT_ROOT / "frontend" / "app.js"
        self.assertTrue(app_path.exists(), "frontend/app.js should exist")

        app_text = app_path.read_text()

        self.assertIn("/api/overview", app_text)
        self.assertIn("/api/filters", app_text)
        self.assertIn("/api/focus-tags/articles", app_text)
        self.assertIn("/api/articles", app_text)
        self.assertIn("/api/articles/", app_text)
        self.assertIn("/api/document-processing", app_text)
        self.assertIn("/api/article-processing", app_text)
        self.assertIn("/api/gmail/import", app_text)
        self.assertIn("articles-processing", app_text)
        self.assertIn("article-processing/", app_text)
        self.assertIn("buildArticleProcessingQueryString", app_text)
        self.assertIn("requestManualArticleRetry", app_text)
        self.assertIn("detailImageGallery", app_text)
        self.assertIn("detail.images", app_text)
        self.assertIn("待翻译文章", app_text)
        self.assertIn("overview.pending_article_count", app_text)
        self.assertIn("showDocumentProcessingPage", app_text)
        self.assertIn("showArticleProcessingPage", app_text)
        self.assertIn("loadArticleProcessing", app_text)
        self.assertIn("loadArticleProcessingDetail", app_text)
        self.assertIn("showArticleProcessingDetail", app_text)
        self.assertIn("article-processing-open-document-button", app_text)
        self.assertIn("article-processing-open-article-button", app_text)
        self.assertIn("articleProcessingDetailBadges", app_text)
        self.assertIn("articleProcessingDetailFields", app_text)
        self.assertIn("articleProcessingRetryButton.disabled", app_text)
        self.assertIn("showDocumentDetail", app_text)
        self.assertIn("renderDocumentVisibleArticles", app_text)
        self.assertIn("documentIdentityFields", app_text)
        self.assertIn("documentErrorSummary", app_text)
        self.assertIn("openSourceDocumentFromArticleDetail", app_text)
        self.assertIn("requestManualRetry", app_text)
        self.assertIn("requestManualGmailImport", app_text)
        self.assertIn("manualGmailImportButton.disabled = true", app_text)
        self.assertIn("manualGmailImportButton.disabled = false", app_text)
        self.assertIn("manualGmailImportStatus", app_text)
        self.assertIn("await loadDocumentProcessing()", app_text)
        self.assertIn("document/", app_text)
        self.assertIn("window.location.hash", app_text)
        self.assertIn("showArticleDetail", app_text)

    def test_frontend_styles_workbench_manual_import_action(self) -> None:
        styles_path = PROJECT_ROOT / "frontend" / "styles.css"
        self.assertTrue(styles_path.exists(), "frontend/styles.css should exist")

        styles_text = styles_path.read_text()

        self.assertIn(".workbench-action-row", styles_text)
        self.assertIn(".manual-gmail-import-status", styles_text)
        self.assertIn(".manual-gmail-import-button", styles_text)

    def test_compose_includes_a_frontend_service(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist")

        compose_text = compose_path.read_text()

        self.assertIn("frontend:", compose_text)
        self.assertIn('${FRONTEND_PORT:-3000}:3000', compose_text)


    def test_frontend_index_and_app_define_processing_selection_flow(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()

        self.assertIn('id="article-processing-selection-count"', index_text)
        self.assertIn("selectedArticleProcessingKeys", app_text)
        self.assertIn("requestBatchArticleRetry", app_text)
        self.assertIn("articleProcessingRetryFilteredButton", app_text)

    def test_frontend_app_requests_pagination_filter_and_batch_retry_surfaces(self) -> None:
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()

        self.assertIn("/api/article-processing/filter-options", app_text)
        self.assertIn("/api/article-processing/retry-batch", app_text)
        self.assertIn("reading-status-filter", app_text)
        self.assertIn("processing-status-filter", app_text)
        self.assertIn("article-processing-step-filter", app_text)
        self.assertIn("article-processing-error-filter", app_text)
        self.assertIn("page_size", app_text)
        self.assertIn("URLSearchParams", app_text)

    def test_frontend_index_defines_pagination_and_batch_retry_controls(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()

        self.assertIn('id="reading-status-filter"', index_text)
        self.assertIn('id="processing-status-filter"', index_text)
        self.assertIn('id="all-articles-pagination"', index_text)
        self.assertIn('id="article-processing-step-filter"', index_text)
        self.assertIn('id="article-processing-error-filter"', index_text)
        self.assertIn('id="article-processing-batch-bar"', index_text)
        self.assertIn('id="article-processing-retry-selected-button"', index_text)
        self.assertIn('id="article-processing-retry-filtered-button"', index_text)


    def test_article_processing_tab_can_hide_document_status_row(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()
        self.assertIn('id="document-processing-filter-form"', index_text)
        self.assertIn("documentProcessingFilterForm", app_text)

    def test_failure_count_filters_present_for_documents_and_articles(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()
        self.assertIn('id="document-failure-count-filter"', index_text)
        self.assertIn('id="article-processing-failure-count-filter"', index_text)
        self.assertIn("renderFailureCountOptions", app_text)
        self.assertIn("min_failure_count", app_text)

    def test_article_processing_detail_has_inline_article_reader(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()
        self.assertIn('id="ap-detail-tab-processing"', index_text)
        self.assertIn('id="ap-detail-tab-article"', index_text)
        self.assertIn('id="ap-reader-single-body"', index_text)
        self.assertIn('id="ap-reader-compare-pane"', index_text)
        self.assertIn("createArticleReader", app_text)

    def test_article_card_template_includes_hero_image(self) -> None:
        index_path = PROJECT_ROOT / "frontend" / "index.html"
        index_text = index_path.read_text()
        self.assertIn('class="card-hero"', index_text)

        styles_path = PROJECT_ROOT / "frontend" / "styles.css"
        self.assertIn(".card-hero", styles_path.read_text())

        app_path = PROJECT_ROOT / "frontend" / "app.js"
        self.assertIn("hero_image_url", app_path.read_text())


if __name__ == "__main__":
    unittest.main()
