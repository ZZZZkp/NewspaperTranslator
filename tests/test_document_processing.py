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

try:
    from newspaper_translator.document_processing import (
        claim_document_processing_run,
        create_document_processing_run,
        create_scheduler_run,
        get_document_processing_run,
        finalize_scheduler_run,
        get_scheduler_run,
        list_eligible_document_processing_runs,
    )
except ImportError:
    claim_document_processing_run = None
    create_document_processing_run = None
    create_scheduler_run = None
    finalize_scheduler_run = None
    get_document_processing_run = None
    get_scheduler_run = None
    list_eligible_document_processing_runs = None


class SchedulerRunStoreTests(unittest.TestCase):
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

    def test_claims_one_eligible_document_processing_run_without_double_claim(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(get_document_processing_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )

            created_run = create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            claimed_run = claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            second_claim = claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-2",
                lock_timeout_seconds=600,
            )
            stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(created_run.status, "pending")
        self.assertEqual(created_run.current_step, "parse_persist")
        self.assertIsNotNone(claimed_run)
        self.assertEqual(claimed_run.status, "running")
        self.assertEqual(claimed_run.locked_by, "worker-1")
        self.assertIsNotNone(claimed_run.lock_expires_at)
        self.assertIsNone(second_claim)
        self.assertEqual(stored_run.status, "running")
        self.assertEqual(stored_run.locked_by, "worker-1")

    def test_create_document_processing_run_is_idempotent_for_same_document(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )

            first_run = create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            second_run = create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(first_run.processing_run_id, second_run.processing_run_id)
        self.assertEqual(second_run.status, "pending")
        self.assertEqual(second_run.current_step, "parse_persist")

    def test_lists_eligible_document_processing_runs_with_manual_retry_priority(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(list_eligible_document_processing_runs)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            manual_retry_key = self._insert_document(database_path, "message-1:attachment-1:hash-1")
            pending_key = self._insert_document(database_path, "message-2:attachment-1:hash-2")
            retryable_key = self._insert_document(database_path, "message-3:attachment-1:hash-3")
            running_key = self._insert_document(database_path, "message-4:attachment-1:hash-4")
            terminal_key = self._insert_document(database_path, "message-5:attachment-1:hash-5")

            create_document_processing_run(database_url=database_url, document_key=manual_retry_key)
            create_document_processing_run(database_url=database_url, document_key=pending_key)
            create_document_processing_run(database_url=database_url, document_key=retryable_key)
            create_document_processing_run(database_url=database_url, document_key=running_key)
            create_document_processing_run(database_url=database_url, document_key=terminal_key)

            self._set_document_processing_status(
                database_path=database_path,
                document_key=manual_retry_key,
                status="manual_retry_requested",
            )
            self._set_document_processing_status(
                database_path=database_path,
                document_key=retryable_key,
                status="failed_retryable",
            )
            self._set_document_processing_status(
                database_path=database_path,
                document_key=running_key,
                status="running",
            )
            self._set_document_processing_status(
                database_path=database_path,
                document_key=terminal_key,
                status="failed_terminal",
            )

            eligible_runs = list_eligible_document_processing_runs(
                database_url=database_url,
                limit=10,
            )

        self.assertEqual(
            [run.document_key for run in eligible_runs],
            [manual_retry_key, pending_key, retryable_key],
        )

    def _insert_document(self, database_path: pathlib.Path, document_key: str) -> str:
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
                    "wsj-2026-04-20.pdf",
                    document_key.split(":")[-1],
                    "/tmp/wsj-2026-04-20.pdf",
                    "imported",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key

    def _set_document_processing_status(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        status: str,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                UPDATE document_processing_runs
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE document_key = ?
                """,
                (status, document_key),
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
