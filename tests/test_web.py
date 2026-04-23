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
    from newspaper_translator.web import create_app
except ImportError:
    create_app = None
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


def _perform_wsgi_request(app, *, path: str) -> tuple[str, dict[str, str], bytes]:
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
            "wsgi.input": None,
        },
        start_response,
    )
    body = b"".join(response_iterable)
    return captured_status, dict(captured_headers), body


if __name__ == "__main__":
    unittest.main()
