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
    from newspaper_translator.worker import build_startup_report, build_startup_log_line
except ImportError:
    build_startup_log_line = None
    build_startup_report = None
    run_pending_migrations = None


class WorkerStartupTests(unittest.TestCase):
    def test_builds_a_worker_startup_report_with_database_status(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            build_startup_report,
            "build_startup_report should be importable from newspaper_translator.worker",
        )
        self.assertIsNotNone(
            build_startup_log_line,
            "build_startup_log_line should be importable from newspaper_translator.worker",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            env = {
                "APP_ENV": "test",
                "DATABASE_URL": database_url,
                "STORAGE_ROOT": temp_dir,
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            }

            report = build_startup_report(env)
            log_line = build_startup_log_line(env, timestamp="2026-04-22T13:10:00Z")

        payload = json.loads(log_line)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["service"], "worker")
        self.assertEqual(report["app_env"], "test")
        self.assertEqual(report["database"]["status"], "ok")
        self.assertEqual(payload["event"], "worker.startup")
        self.assertEqual(payload["service"], "worker")
        self.assertEqual(payload["details"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
