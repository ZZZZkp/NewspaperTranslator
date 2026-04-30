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
        self.assertIn('id="document-detail-view"', index_text)
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
        self.assertIn("detailImageGallery", app_text)
        self.assertIn("detail.images", app_text)
        self.assertIn("待翻译文章", app_text)
        self.assertIn("overview.pending_article_count", app_text)
        self.assertIn("showDocumentProcessingPage", app_text)
        self.assertIn("showDocumentDetail", app_text)
        self.assertIn("renderDocumentVisibleArticles", app_text)
        self.assertIn("documentIdentityFields", app_text)
        self.assertIn("documentErrorSummary", app_text)
        self.assertIn("openSourceDocumentFromArticleDetail", app_text)
        self.assertIn("requestManualRetry", app_text)
        self.assertIn("document/", app_text)
        self.assertIn("window.location.hash", app_text)
        self.assertIn("showArticleDetail", app_text)

    def test_compose_includes_a_frontend_service(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist")

        compose_text = compose_path.read_text()

        self.assertIn("frontend:", compose_text)
        self.assertIn('${FRONTEND_PORT:-3000}:3000', compose_text)


if __name__ == "__main__":
    unittest.main()
