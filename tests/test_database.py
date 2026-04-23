import pathlib
import sqlite3
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
except ImportError:
    run_pending_migrations = None


class DatabaseMigrationTests(unittest.TestCase):
    def test_applies_initial_schema_migration_to_sqlite_database(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0001_initial", applied_versions)
        self.assertIn("schema_migrations", table_names)
        self.assertIn("documents", table_names)
        self.assertIn("processing_tasks", table_names)
        self.assertIn("0001_initial", recorded_versions)

    def test_applies_import_audit_schema_migration_to_sqlite_database(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0002_import_audit", applied_versions)
        self.assertIn("import_runs", table_names)
        self.assertIn("import_run_items", table_names)
        self.assertIn("0002_import_audit", recorded_versions)

    def test_applies_checkpoint_and_retry_schema_migration_to_sqlite_database(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            applied_versions = run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                import_runs_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(import_runs)")
                }
                import_run_items_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(import_run_items)")
                }
                failed_messages_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(failed_messages)")
                }
                import_checkpoints_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(import_checkpoints)")
                }
                recorded_versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
            finally:
                connection.close()

        self.assertIn("0003_checkpointing_retry", applied_versions)
        self.assertIn("failed_messages", table_names)
        self.assertIn("import_checkpoints", table_names)
        self.assertIn("checkpoint_before", import_runs_columns)
        self.assertIn("checkpoint_after", import_runs_columns)
        self.assertIn("message_internal_date", import_run_items_columns)
        self.assertIn("retry_state", failed_messages_columns)
        self.assertIn("retry_attempt_count", failed_messages_columns)
        self.assertIn("checkpoint_value", import_checkpoints_columns)
        self.assertEqual(
            recorded_versions,
            ["0001_initial", "0002_import_audit", "0003_checkpointing_retry"],
        )


if __name__ == "__main__":
    unittest.main()
