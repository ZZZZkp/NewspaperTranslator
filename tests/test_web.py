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
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.import_audit import (
        create_import_run,
        finalize_import_run,
        record_import_run_retry_summary,
        record_import_run_item,
    )
    from newspaper_translator.document_processing import (
        create_document_processing_run,
        request_manual_document_retry,
    )
    from newspaper_translator.web import create_app
except ImportError:
    create_app = None
    create_document_processing_run = None
    create_import_run = None
    finalize_import_run = None
    record_import_run_retry_summary = None
    record_import_run_item = None
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

    def _insert_document(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        raw_path: str = "/tmp/wsj-2026-04-20.pdf",
        original_filename: str = "wsj-2026-04-20.pdf",
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
                    "gmail",
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
