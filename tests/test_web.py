import json
import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.api.queries import (
        get_article_detail_view,
        get_filter_options_view,
        get_overview_view,
        list_focus_tag_article_card_views,
    )
    from newspaper_translator.article_store import (
        create_article_enrichment_run,
        create_parse_run,
        finalize_article_enrichment_run,
        finalize_parse_run,
        list_parse_run_final_articles,
        record_article_enrichment_outputs,
        record_parse_run_result,
    )
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.import_audit import (
        create_import_run,
        finalize_import_run,
        record_import_run_retry_summary,
        record_import_run_item,
    )
    from newspaper_translator.document_processing import (
        create_article_processing_run,
        create_document_processing_run,
        request_manual_article_retry,
        request_manual_document_retry,
    )
    from newspaper_translator.web import create_app
except ImportError:
    create_article_enrichment_run = None
    create_app = None
    create_parse_run = None
    create_article_processing_run = None
    create_document_processing_run = None
    create_import_run = None
    get_article_detail_view = None
    get_filter_options_view = None
    finalize_article_enrichment_run = None
    finalize_parse_run = None
    get_overview_view = None
    list_focus_tag_article_card_views = None
    list_parse_run_final_articles = None
    finalize_import_run = None
    record_article_enrichment_outputs = None
    record_import_run_retry_summary = None
    record_import_run_item = None
    record_parse_run_result = None
    request_manual_article_retry = None
    request_manual_document_retry = None
    run_pending_migrations = None


class WebHealthEndpointTests(unittest.TestCase):
    def test_health_endpoint_initializes_database_before_reporting_status(self) -> None:
        self.assertIsNotNone(
            create_app,
            "create_app should be importable from newspaper_translator.web",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(app, path="/healthz")
            self.assertTrue(database_path.exists())

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["database"]["status"], "ok")
        self.assertGreaterEqual(payload["database"]["applied_migration_count"], 1)

    def test_health_endpoint_returns_ok_when_database_is_ready(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            create_app,
            "create_app should be importable from newspaper_translator.web",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, headers, body = _perform_wsgi_request(app, path="/healthz")

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["app_env"], "test")
        self.assertEqual(payload["database"]["status"], "ok")
        self.assertEqual(payload["database"]["driver"], "sqlite")

    def test_import_runs_endpoint_returns_recent_runs(self) -> None:
        self.assertIsNotNone(create_import_run)
        self.assertIsNotNone(finalize_import_run)
        self.assertIsNotNone(record_import_run_retry_summary)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=run.run_id,
                fetched_message_count=2,
                imported_attachment_count=1,
                created_document_count=1,
                skipped_document_count=0,
            )
            record_import_run_retry_summary(
                database_url=database_url,
                run_id=run.run_id,
                retry_run_id="retry-run-1",
                retried_message_count=2,
                resolved_message_count=1,
                failed_final_message_count=1,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(app, path="/import-runs")

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, "200 OK")
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["run_id"], run.run_id)
        self.assertEqual(payload["runs"][0]["status"], "succeeded")
        self.assertTrue(payload["runs"][0]["retry_performed"])
        self.assertEqual(payload["runs"][0]["retry_run_id"], "retry-run-1")
        self.assertEqual(payload["runs"][0]["retried_message_count"], 2)
        self.assertEqual(payload["runs"][0]["resolved_message_count"], 1)
        self.assertEqual(payload["runs"][0]["failed_final_message_count"], 1)

    def test_import_run_items_and_import_items_endpoints_support_filters(self) -> None:
        self.assertIsNotNone(create_import_run)
        self.assertIsNotNone(record_import_run_item)
        self.assertIsNotNone(finalize_import_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=run.run_id,
                item_type="attachment",
                item_key="message:1:attachment:1",
                message_id="message-1",
                attachment_id="attachment-1",
                link_url=None,
                status="succeeded",
                detail_code="document_created",
                detail_message="Attachment imported.",
                document_key="message-1:attachment-1:abc",
            )
            record_import_run_item(
                database_url=database_url,
                run_id=run.run_id,
                item_type="body_link",
                item_key="message:1:body_link:https://example.com/bad",
                message_id="message-1",
                attachment_id=None,
                link_url="https://example.com/bad",
                status="failed",
                detail_code="link_fetch_failed",
                detail_message="Upstream SSL failure.",
                document_key=None,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=run.run_id,
                fetched_message_count=1,
                imported_attachment_count=1,
                created_document_count=1,
                skipped_document_count=0,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status_run_items, _, body_run_items = _perform_wsgi_request(
                app,
                path=f"/import-runs/{run.run_id}/items",
                query_string="status=failed",
            )
            status_items, _, body_items = _perform_wsgi_request(
                app,
                path="/import-items",
                query_string="status=failed&item_type=body_link",
            )

        run_items_payload = json.loads(body_run_items.decode("utf-8"))
        items_payload = json.loads(body_items.decode("utf-8"))

        self.assertEqual(status_run_items, "200 OK")
        self.assertEqual([item["item_type"] for item in run_items_payload["items"]], ["body_link"])
        self.assertEqual(status_items, "200 OK")
        self.assertEqual([item["detail_code"] for item in items_payload["items"]], ["link_fetch_failed"])

    def test_document_processing_endpoints_return_current_state_and_support_retry(self) -> None:
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(request_manual_document_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            request_manual_document_retry(
                database_url=database_url,
                document_key=document_key,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status_list, _, body_list = _perform_wsgi_request(
                app,
                path="/document-processing",
            )
            status_one, _, body_one = _perform_wsgi_request(
                app,
                path=f"/document-processing/{document_key}",
            )
            status_retry, _, body_retry = _perform_wsgi_request(
                app,
                method="POST",
                path=f"/document-processing/{document_key}/retry",
            )

        list_payload = json.loads(body_list.decode("utf-8"))
        one_payload = json.loads(body_one.decode("utf-8"))
        retry_payload = json.loads(body_retry.decode("utf-8"))

        self.assertEqual(status_list, "200 OK")
        self.assertEqual([item["document_key"] for item in list_payload["runs"]], [document_key])
        self.assertEqual(list_payload["runs"][0]["status"], "manual_retry_requested")
        self.assertEqual(status_one, "200 OK")
        self.assertEqual(one_payload["run"]["document_key"], document_key)
        self.assertEqual(one_payload["run"]["status"], "manual_retry_requested")
        self.assertEqual(status_retry, "200 OK")
        self.assertEqual(retry_payload["run"]["document_key"], document_key)
        self.assertEqual(retry_payload["run"]["status"], "manual_retry_requested")

    def test_api_document_processing_endpoints_return_current_state_and_support_retry(self) -> None:
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(request_manual_document_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            request_manual_document_retry(
                database_url=database_url,
                document_key=document_key,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status_list, _, body_list = _perform_wsgi_request(
                app,
                path="/api/document-processing",
            )
            status_one, _, body_one = _perform_wsgi_request(
                app,
                path=f"/api/document-processing/{document_key}",
            )
            status_retry, _, body_retry = _perform_wsgi_request(
                app,
                method="POST",
                path=f"/api/document-processing/{document_key}/retry",
            )

        list_payload = json.loads(body_list.decode("utf-8"))
        one_payload = json.loads(body_one.decode("utf-8"))
        retry_payload = json.loads(body_retry.decode("utf-8"))

        self.assertEqual(status_list, "200 OK")
        self.assertEqual([item["document_key"] for item in list_payload["runs"]], [document_key])
        self.assertEqual(list_payload["runs"][0]["status"], "manual_retry_requested")
        self.assertEqual(status_one, "200 OK")
        self.assertEqual(one_payload["run"]["document_key"], document_key)
        self.assertEqual(one_payload["run"]["status"], "manual_retry_requested")
        self.assertEqual(status_retry, "200 OK")
        self.assertEqual(retry_payload["run"]["document_key"], document_key)
        self.assertEqual(retry_payload["run"]["status"], "manual_retry_requested")

    def test_api_article_processing_endpoints_return_current_state_and_support_retry(self) -> None:
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(request_manual_article_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
            )
            article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            article_key = self._get_article_key(
                database_path=database_path,
                article_id=article_id,
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=article_id,
            )
            request_manual_article_retry(
                database_url=database_url,
                article_key=article_key,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status_list, _, body_list = _perform_wsgi_request(
                app,
                path="/api/article-processing",
            )
            status_one, _, body_one = _perform_wsgi_request(
                app,
                path=f"/api/article-processing/{article_key}",
            )
            status_retry, _, body_retry = _perform_wsgi_request(
                app,
                method="POST",
                path=f"/api/article-processing/{article_key}/retry",
            )

        list_payload = json.loads(body_list.decode("utf-8"))
        one_payload = json.loads(body_one.decode("utf-8"))
        retry_payload = json.loads(body_retry.decode("utf-8"))

        self.assertEqual(status_list, "200 OK")
        self.assertEqual([item["article_key"] for item in list_payload["runs"]], [article_key])
        self.assertEqual(list_payload["runs"][0]["status"], "manual_retry_requested")
        self.assertEqual(
            list_payload["runs"][0]["title_en"],
            "Chipmakers prepare for a new subsidy dispute",
        )
        self.assertEqual(list_payload["runs"][0]["source_name"], "gmail")
        self.assertEqual(list_payload["runs"][0]["original_filename"], "wsj-2026-04-20.pdf")
        self.assertEqual(list_payload["runs"][0]["publication_date"], "2026-04-22")
        self.assertEqual(list_payload["runs"][0]["source_page_numbers"], [0])
        self.assertEqual(
            list_payload["runs"][0]["latest_error_summary"],
            "当前没有错误。",
        )
        self.assertEqual(status_one, "200 OK")
        self.assertEqual(one_payload["run"]["article_key"], article_key)
        self.assertEqual(one_payload["run"]["status"], "manual_retry_requested")
        self.assertEqual(one_payload["run"]["title_en"], "Chipmakers prepare for a new subsidy dispute")
        self.assertEqual(status_retry, "200 OK")
        self.assertEqual(retry_payload["run"]["article_key"], article_key)
        self.assertEqual(retry_payload["run"]["status"], "manual_retry_requested")

    def test_article_processing_list_endpoint_supports_status_filter(self) -> None:
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(request_manual_article_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            retry_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
            )
            pending_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
            )
            retry_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=retry_document_key,
                publication_date="2026-04-22",
                title="Retry article",
                body_suffix="Retry body.",
                translated_title_zh="重试文章",
                summary_zh="重试摘要",
                translated_body_zh="重试正文。",
                tags=["Retry", "Policy", "Operations"],
            )
            pending_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=pending_document_key,
                publication_date="2026-04-22",
                title="Pending article",
                body_suffix="Pending body.",
                translated_title_zh="待处理文章",
                summary_zh="待处理摘要",
                translated_body_zh="待处理正文。",
                tags=["Pending", "Queue", "Operations"],
            )
            retry_article_key = self._get_article_key(
                database_path=database_path,
                article_id=retry_article_id,
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=retry_article_id,
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=pending_article_id,
            )
            request_manual_article_retry(
                database_url=database_url,
                article_key=retry_article_key,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/article-processing",
                query_string="status=manual_retry_requested",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual([item["article_key"] for item in payload["runs"]], [retry_article_key])

    def test_article_processing_list_endpoint_supports_source_and_date_filters(self) -> None:
        self.assertIsNotNone(create_article_processing_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )
            second_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-24.pdf",
                source_name="Wall Street Journal",
            )
            first_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="First article",
                body_suffix="First body.",
                translated_title_zh="第一篇文章",
                summary_zh="第一篇摘要",
                translated_body_zh="第一篇正文。",
                tags=["First", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-24",
                title="Second article",
                body_suffix="Second body.",
                translated_title_zh="第二篇文章",
                summary_zh="第二篇摘要",
                translated_body_zh="第二篇正文。",
                tags=["Second", "Policy", "Trade"],
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=first_article_id,
            )
            second_article_key = self._get_article_key(
                database_path=database_path,
                article_id=second_article_id,
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=second_article_id,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/article-processing",
                query_string="source=Wall%20Street%20Journal&publication_date_from=2026-04-23&publication_date_to=2026-04-24",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual([item["article_key"] for item in payload["runs"]], [second_article_key])

    def test_api_document_processing_detail_endpoint_includes_visible_articles(self) -> None:
        self.assertIsNotNone(create_parse_run)
        self.assertIsNotNone(create_article_enrichment_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            first_article = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            self._insert_document_processing_run(
                database_path=database_path,
                document_key=document_key,
                status="succeeded",
                current_step="completed",
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path=f"/api/document-processing/{document_key}",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["run"]["document_key"], document_key)
        self.assertEqual(payload["run"]["visible_article_count"], 1)
        self.assertEqual(payload["run"]["visible_articles"][0]["article_id"], first_article)
        self.assertEqual(
            payload["run"]["visible_articles"][0]["title_zh"],
            "芯片制造商准备应对新的补贴争端",
        )
        self.assertEqual(payload["run"]["source_name"], "Financial Times")
        self.assertEqual(payload["run"]["original_filename"], "ft-2026-04-22.pdf")
        self.assertEqual(payload["run"]["sender"], "news@example.com")
        self.assertEqual(payload["run"]["import_status"], "imported")
        self.assertEqual(payload["run"]["latest_error_summary"], "当前没有错误。")

    def test_document_processing_list_endpoint_supports_status_filter(self) -> None:
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(request_manual_document_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            retry_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
            )
            pending_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=retry_key,
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=pending_key,
            )
            request_manual_document_retry(
                database_url=database_url,
                document_key=retry_key,
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/document-processing",
                query_string="status=manual_retry_requested",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual([item["document_key"] for item in payload["runs"]], [retry_key])

    def test_articles_endpoint_returns_article_cards(self) -> None:
        self.assertIsNotNone(create_parse_run)
        self.assertIsNotNone(create_article_enrichment_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=document_key,
                publication_date="2026-04-22",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]
            enrichment_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="succeeded",
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/articles",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(len(payload["articles"]), 1)
        self.assertEqual(payload["articles"][0]["title_zh"], "芯片制造商准备应对新的补贴争端")
        self.assertEqual(payload["articles"][0]["tags"], ["Semiconductors", "Policy", "Trade"])

    def test_overview_endpoint_returns_dashboard_summary_counts(self) -> None:
        self.assertIsNotNone(get_overview_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            self._insert_import_run(database_path=database_path, created_document_count=2)
            doc_running = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
            )
            doc_retryable = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-22.pdf",
            )
            self._insert_document_processing_run(
                database_path=database_path,
                document_key=doc_running,
                status="running",
                current_step="parse_persist",
            )
            self._insert_document_processing_run(
                database_path=database_path,
                document_key=doc_retryable,
                status="failed_retryable",
                current_step="enrich",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=doc_running,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=doc_running,
                publication_date="2026-04-22",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/overview",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["overview"]["imported_document_count"], 2)
        self.assertEqual(payload["overview"]["article_count"], 1)
        self.assertEqual(payload["overview"]["pending_article_count"], 1)
        self.assertEqual(payload["overview"]["processing_document_count"], 1)
        self.assertEqual(payload["overview"]["pending_exception_count"], 1)

    def test_article_detail_endpoint_returns_bilingual_payload(self) -> None:
        self.assertIsNotNone(get_article_detail_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=document_key,
                publication_date="2026-04-22",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]
            enrichment_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="succeeded",
            )
            self._insert_document_processing_run(
                database_path=database_path,
                document_key=document_key,
                status="succeeded",
                current_step="completed",
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path=f"/api/articles/{article.article_id}",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["article"]["title_zh"], "芯片制造商准备应对新的补贴争端")
        self.assertEqual(payload["article"]["processing"]["latest_enrichment_status"], "succeeded")

    def test_filters_endpoint_returns_distinct_sources_and_tags(self) -> None:
        self.assertIsNotNone(get_filter_options_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )
            second_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Policy", "Hardware", "Trade"],
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/filters",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["filters"]["sources"], ["Financial Times", "Wall Street Journal"])
        self.assertEqual(payload["filters"]["tags"], ["Hardware", "Policy", "Semiconductors", "Trade"])

    def test_articles_endpoint_supports_source_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )
            second_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Policy", "Hardware", "Trade"],
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/articles",
                query_string="source=Wall%20Street%20Journal",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(len(payload["articles"]), 1)
        self.assertEqual(payload["articles"][0]["article_id"], second_article_id)

    def test_articles_endpoint_supports_tag_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )
            second_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Policy", "Hardware", "Trade"],
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/articles",
                query_string="tag=Hardware",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(len(payload["articles"]), 1)
        self.assertEqual(payload["articles"][0]["article_id"], second_article_id)

    def test_focus_tag_articles_endpoint_returns_articles_matching_configured_focus_tags(self) -> None:
        self.assertIsNotNone(list_focus_tag_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )
            second_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
            )
            third_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-3:attachment-1:hash-3",
                original_filename="econ-2026-04-22.pdf",
                source_name="The Economist",
            )
            first_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Hardware", "Trade", "Policy"],
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=third_document_key,
                publication_date="2026-04-22",
                title="Cities recover commuter traffic",
                body_suffix="Urban planners are reassessing transport demand.",
                translated_title_zh="城市正在恢复通勤流量",
                summary_zh="城市规划者正在重新评估交通需求。",
                translated_body_zh="随着通勤回暖，城市交通系统正在重新分配资源。",
                tags=["Cities", "Transport", "Urbanism"],
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                    "FOCUS_TAGS": "Semiconductors, Hardware",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/focus-tags/articles",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(
            [item["article_id"] for item in payload["articles"]],
            [first_article_id, second_article_id],
        )

    def test_articles_endpoint_supports_publication_date_range_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            older_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-1:attachment-1:hash-1",
                original_filename="ft-2026-04-21.pdf",
                source_name="Financial Times",
            )
            newer_document_key = self._insert_document(
                database_path=database_path,
                document_key="message-2:attachment-1:hash-2",
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=older_document_key,
                publication_date="2026-04-21",
                title="Older article",
                body_suffix="Older article body.",
                translated_title_zh="较早文章",
                summary_zh="较早文章摘要。",
                translated_body_zh="较早文章正文。",
                tags=["Markets", "Europe", "Trade"],
            )
            newer_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=newer_document_key,
                publication_date="2026-04-22",
                title="Newer article",
                body_suffix="Newer article body.",
                translated_title_zh="较新文章",
                summary_zh="较新文章摘要。",
                translated_body_zh="较新文章正文。",
                tags=["Policy", "Hardware", "Trade"],
            )

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                }
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/articles",
                query_string="publication_date_from=2026-04-22&publication_date_to=2026-04-22",
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, "200 OK")
        self.assertEqual(len(payload["articles"]), 1)
        self.assertEqual(payload["articles"][0]["article_id"], newer_article_id)

    def _insert_document(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        raw_path: str = "/tmp/wsj-2026-04-20.pdf",
        original_filename: str = "wsj-2026-04-20.pdf",
        source_name: str = "gmail",
    ) -> str:
        import sqlite3

        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO documents (
                    document_key,
                    source_name,
                    source_message_id,
                    source_attachment_id,
                    sender,
                    original_filename,
                    content_hash,
                    raw_path,
                    import_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_key,
                    source_name,
                    document_key.split(":")[0],
                    "attachment-1",
                    "news@example.com",
                    original_filename,
                    document_key.split(":")[-1],
                    raw_path,
                    "imported",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key

    def _insert_import_run(self, *, database_path: pathlib.Path, created_document_count: int) -> str:
        import sqlite3

        run_id = "import-run-1"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO import_runs (
                    run_id,
                    source_name,
                    status,
                    query,
                    allowed_senders_json,
                    max_results,
                    created_document_count,
                    finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    run_id,
                    "gmail",
                    "succeeded",
                    "newer_than:7d",
                    "[]",
                    25,
                    created_document_count,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return run_id

    def _insert_document_processing_run(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        status: str,
        current_step: str,
    ) -> None:
        import sqlite3

        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO document_processing_runs (
                    processing_run_id,
                    document_key,
                    status,
                    current_step
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    f"processing-{document_key}",
                    document_key,
                    status,
                    current_step,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _get_article_key(
        self,
        *,
        database_path: pathlib.Path,
        article_id: str,
    ) -> str:
        import sqlite3

        connection = sqlite3.connect(database_path)
        try:
            row = connection.execute(
                """
                SELECT article_key
                FROM final_articles
                WHERE article_id = ?
                """,
                (article_id,),
            ).fetchone()
        finally:
            connection.close()
        return row[0]

    def _build_parse_result(self, *, title: str, body_suffix: str):
        from newspaper_translator.pdf import (
            ArticleFragment,
            ArticleSource,
            ParseMatchDecision,
            ParseResult,
            ParsedArticle,
        )

        return ParseResult(
            fragments=[
                ArticleFragment(
                    title=title,
                    body_text="The policy outlook shifted rapidly.\nPlease turn to page A7",
                    source_order=1,
                    continued_to_page="A7",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Chipmakers prepare",
                    body_text=(
                        "Continued from PageOne after new proposals were circulated.\n"
                        f"{body_suffix}"
                    ),
                    source_order=2,
                    continued_to_page="",
                    continued_from_page="PageOne",
                ),
            ],
            match_decisions=[
                ParseMatchDecision(
                    front_source_order=1,
                    back_source_order=2,
                    decision_status="accepted",
                    decision_reason="accepted continuation pair",
                    matcher_raw_response="(1, 2)",
                )
            ],
            articles=[
                ParsedArticle(
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=2,
                    title=title,
                    body_text=(
                        "The policy outlook shifted rapidly.\n"
                        f"{body_suffix}"
                    ),
                    source_fragments=[
                        ArticleSource(source_order=1, fragment_role="front", sequence_index=1),
                        ArticleSource(source_order=2, fragment_role="back", sequence_index=2),
                    ],
                )
            ],
        )

    def _insert_succeeded_article_with_enrichment(
        self,
        *,
        database_url: str,
        document_key: str,
        publication_date: str,
        title: str,
        body_suffix: str,
        translated_title_zh: str,
        summary_zh: str,
        translated_body_zh: str,
        tags: list[str],
    ) -> str:
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date=publication_date,
            continuation_matcher_name="gemini",
            continuation_matcher_version="2.5-flash",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=self._build_parse_result(
                title=title,
                body_suffix=body_suffix,
            ),
            document_key=document_key,
            publication_date=publication_date,
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )
        article = list_parse_run_final_articles(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
        )[0]
        enrichment_run = create_article_enrichment_run(
            database_url=database_url,
            article_id=article.article_id,
            parse_run_id=parse_run.parse_run_id,
            provider_name="gemini",
            model_name="gemini-2.5-flash",
            prompt_version="article-enrichment-v2",
            input_hash=f"hash-{article.article_id}",
        )
        record_article_enrichment_outputs(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            translated_title_zh=translated_title_zh,
            summary_zh=summary_zh,
            translated_body_zh=translated_body_zh,
            translation_status="succeeded",
            summary_status="succeeded",
            tagging_status="succeeded",
            tags=tags,
        )
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="succeeded",
        )
        return article.article_id


def _perform_wsgi_request(app, *, method: str = "GET", path: str, query_string: str = "") -> tuple[str, dict[str, str], bytes]:
    captured_status = ""
    captured_headers: list[tuple[str, str]] = []

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info=None,
    ) -> None:
        nonlocal captured_status, captured_headers
        captured_status = status
        captured_headers = headers

    response_iterable = app(
        {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query_string,
            "wsgi.input": None,
        },
        start_response,
    )
    body = b"".join(response_iterable)
    return captured_status, dict(captured_headers), body


if __name__ == "__main__":
    unittest.main()
