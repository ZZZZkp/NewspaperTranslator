import pathlib
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.manage import run_cli
except ImportError:
    run_cli = None


class ManagementCommandTests(unittest.TestCase):
    def test_gmail_import_command_uses_config_file_and_reports_summary(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = pathlib.Path(temp_dir) / "gmail-config.json"
            config_path.write_text("{}")

            with patch("newspaper_translator.manage.import_from_gmail") as import_from_gmail:
                import_from_gmail.return_value = SimpleNamespace(
                    fetched_message_count=3,
                    imported_attachment_count=2,
                    created_document_count=1,
                    skipped_document_count=1,
                )

                exit_code, output = run_cli(
                    [
                        "gmail-import",
                        "--gmail-config",
                        str(config_path),
                        "--database-url",
                        "sqlite:////tmp/newspaper-translator.db",
                        "--storage-root",
                        "/tmp/newspaper-translator-data",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn('"fetched_message_count": 3', output)
        self.assertIn('"created_document_count": 1', output)

    def test_check_command_can_read_runtime_settings_from_environment(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            with patch.dict(
                "os.environ",
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CLIENT_ID": "client-id",
                    "GMAIL_CLIENT_SECRET": "client-secret",
                    "GMAIL_REFRESH_TOKEN": "refresh-token",
                },
                clear=False,
            ):
                exit_code, output = run_cli(["check", "--service", "worker"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"service": "worker"', output)
        self.assertIn('"status": "ok"', output)

    def test_check_command_reports_runtime_readiness_for_named_service(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            exit_code, output = run_cli(
                [
                    "check",
                    "--service",
                    "web",
                    "--app-env",
                    "test",
                    "--database-url",
                    database_url,
                    "--storage-root",
                    temp_dir,
                    "--gmail-client-id",
                    "client-id",
                    "--gmail-client-secret",
                    "client-secret",
                    "--gmail-refresh-token",
                    "refresh-token",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"service": "web"', output)
        self.assertIn('"status": "ok"', output)
        self.assertIn('"driver": "sqlite"', output)

    def test_migrate_command_applies_pending_migrations_and_reports_versions(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            exit_code, output = run_cli(
                [
                    "migrate",
                    "--database-url",
                    database_url,
                ]
            )
            self.assertTrue(database_path.exists())

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied migrations: 0001_initial", output)


if __name__ == "__main__":
    unittest.main()
