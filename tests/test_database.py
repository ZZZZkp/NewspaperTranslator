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

        self.assertEqual(applied_versions, ["0001_initial"])
        self.assertIn("schema_migrations", table_names)
        self.assertIn("documents", table_names)
        self.assertIn("processing_tasks", table_names)
        self.assertEqual(recorded_versions, ["0001_initial"])


if __name__ == "__main__":
    unittest.main()
