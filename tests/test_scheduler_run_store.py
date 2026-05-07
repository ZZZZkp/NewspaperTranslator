import pathlib
import sys
import tempfile
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from _document_processing_helpers import (
    DocumentProcessingTestMixin,
    run_pending_migrations,
    create_scheduler_run,
    finalize_scheduler_run,
    get_scheduler_run,
    get_latest_scheduler_run,
)


class SchedulerRunStoreTests(DocumentProcessingTestMixin, unittest.TestCase):
    def test_creates_and_finalizes_a_scheduler_run(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_scheduler_run)
        self.assertIsNotNone(finalize_scheduler_run)
        self.assertIsNotNone(get_scheduler_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            created_run = create_scheduler_run(
                database_url=database_url,
                trigger_type="interval",
            )
            finalize_scheduler_run(
                database_url=database_url,
                scheduler_run_id=created_run.scheduler_run_id,
                status="partial",
                selected_document_count=3,
                completed_document_count=2,
                failed_document_count=1,
                error_message="one document exhausted retries",
            )
            finalized_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=created_run.scheduler_run_id,
            )

        self.assertEqual(created_run.trigger_type, "interval")
        self.assertEqual(created_run.status, "running")
        self.assertIsNone(created_run.finished_at)
        self.assertEqual(finalized_run.status, "partial")
        self.assertEqual(finalized_run.selected_document_count, 3)
        self.assertEqual(finalized_run.completed_document_count, 2)
        self.assertEqual(finalized_run.failed_document_count, 1)
        self.assertEqual(finalized_run.error_message, "one document exhausted retries")
        self.assertIsNotNone(finalized_run.finished_at)

    def test_gets_the_latest_scheduler_run_by_started_at(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_scheduler_run)
        self.assertIsNotNone(get_latest_scheduler_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            first_run = create_scheduler_run(
                database_url=database_url,
                trigger_type="interval",
            )
            second_run = create_scheduler_run(
                database_url=database_url,
                trigger_type="manual",
            )
            self._set_scheduler_run_started_at(
                database_path=database_path,
                scheduler_run_id=first_run.scheduler_run_id,
                started_at="2026-04-28 08:00:00",
            )
            self._set_scheduler_run_started_at(
                database_path=database_path,
                scheduler_run_id=second_run.scheduler_run_id,
                started_at="2026-04-28 10:00:00",
            )

            latest_run = get_latest_scheduler_run(database_url=database_url)

        self.assertIsNotNone(latest_run)
        self.assertEqual(latest_run.scheduler_run_id, second_run.scheduler_run_id)
        self.assertEqual(latest_run.trigger_type, "manual")


if __name__ == "__main__":
    unittest.main()
