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
        record_import_run_item,
    )
    from newspaper_translator.web import create_app
except ImportError:
    create_app = None
    create_import_run = None
    finalize_import_run = None
    record_import_run_item = None
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
                    "GMAIL_CLIENT_ID": "client-id",
                    "GMAIL_CLIENT_SECRET": "client-secret",
                    "GMAIL_REFRESH_TOKEN": "refresh-token",
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
                    "GMAIL_CLIENT_ID": "client-id",
                    "GMAIL_CLIENT_SECRET": "client-secret",
                    "GMAIL_REFRESH_TOKEN": "refresh-token",
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

            app = create_app(
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CLIENT_ID": "client-id",
                    "GMAIL_CLIENT_SECRET": "client-secret",
                    "GMAIL_REFRESH_TOKEN": "refresh-token",
                }
            )

            status, _, body = _perform_wsgi_request(app, path="/import-runs")

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, "200 OK")
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["run_id"], run.run_id)
        self.assertEqual(payload["runs"][0]["status"], "succeeded")

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
                    "GMAIL_CLIENT_ID": "client-id",
                    "GMAIL_CLIENT_SECRET": "client-secret",
                    "GMAIL_REFRESH_TOKEN": "refresh-token",
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


def _perform_wsgi_request(app, *, path: str, query_string: str = "") -> tuple[str, dict[str, str], bytes]:
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
            "REQUEST_METHOD": "GET",
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
