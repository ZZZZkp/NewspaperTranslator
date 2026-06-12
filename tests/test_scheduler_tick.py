import pathlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

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
    document_processing_module,
    create_document_processing_run,
    get_document_processing_run,
    get_scheduler_run,
    run_scheduler_tick,
    run_processing_tick,
    DrainResult,
    list_eligible_document_processing_runs,
    create_scheduler_run,
    finalize_scheduler_run,
    run_document_processing_drain,
    run_article_processing_drain,
)


class SchedulerTickTests(DocumentProcessingTestMixin, unittest.TestCase):
    def test_scheduler_tick_can_continue_retryable_documents_when_gmail_import_finds_nothing_new(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_scheduler_tick)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            self._set_document_processing_status(
                database_path=database_path,
                document_key=document_key,
                status="failed_retryable",
            )

            processed_document_keys: list[str] = []

            def import_documents():
                return SimpleNamespace(run_id="import-run-1", created_document_count=0)

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                processed_document_keys.append(document_key)
                return SimpleNamespace(
                    document_key=document_key,
                    status="succeeded",
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                )

            scheduler_run = run_scheduler_tick(
                database_url=database_url,
                trigger_type="interval",
                import_documents=import_documents,
                process_one_document=process_one_document,
                document_limit=10,
            )
            stored_scheduler_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=scheduler_run.scheduler_run_id,
            )

        self.assertEqual(processed_document_keys, [document_key])
        self.assertEqual(stored_scheduler_run.import_run_id, "import-run-1")
        self.assertEqual(stored_scheduler_run.selected_document_count, 1)
        self.assertEqual(stored_scheduler_run.completed_document_count, 1)
        self.assertEqual(stored_scheduler_run.failed_document_count, 0)
        self.assertEqual(stored_scheduler_run.status, "succeeded")

    def test_processing_tick_processes_documents_without_importing_gmail(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_processing_tick)
        self.assertIsNotNone(get_scheduler_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            processed_document_keys: list[str] = []

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                processed_document_keys.append(document_key)
                return SimpleNamespace(
                    document_key=document_key,
                    status="succeeded",
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                )

            scheduler_run = run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=process_one_document,
                document_limit=10,
            )
            stored_scheduler_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=scheduler_run.scheduler_run_id,
            )

        self.assertEqual(processed_document_keys, [document_key])
        self.assertEqual(stored_scheduler_run.import_run_id, None)
        self.assertEqual(stored_scheduler_run.selected_document_count, 1)
        self.assertEqual(stored_scheduler_run.completed_document_count, 1)
        self.assertEqual(stored_scheduler_run.failed_document_count, 0)
        self.assertEqual(stored_scheduler_run.status, "succeeded")

    def test_processing_tick_finalizes_claimed_document_run_for_generic_success_callback(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_processing_tick)
        self.assertIsNotNone(get_document_processing_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

            scheduler_run = run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=lambda **kwargs: SimpleNamespace(status="succeeded"),
                document_limit=1,
            )
            stored_document_run = get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertTrue(scheduler_run.did_work)
        self.assertEqual(stored_document_run.status, "succeeded")
        self.assertEqual(stored_document_run.current_step, "completed")
        self.assertIsNone(stored_document_run.locked_by)
        self.assertIsNone(stored_document_run.lock_expires_at)

    def test_processing_tick_uses_document_processing_drain_for_document_only_work(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_processing_tick)
        self.assertIsNotNone(get_scheduler_run)
        self.assertIsNotNone(DrainResult)
        self.assertIsNotNone(document_processing_module)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            direct_document_calls: list[str] = []

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                direct_document_calls.append(document_key)
                return SimpleNamespace(status="succeeded")

            with mock.patch.object(
                document_processing_module,
                "run_document_processing_drain",
                return_value=DrainResult(
                    did_work=True,
                    selected_count=7,
                    completed_count=6,
                    failed_count=1,
                    error_messages=("parse timeout",),
                ),
            ) as mocked_document_drain:
                scheduler_run = run_processing_tick(
                    database_url=database_url,
                    trigger_type="processing",
                    process_one_document=process_one_document,
                    document_limit=3,
                )
            stored_scheduler_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=scheduler_run.scheduler_run_id,
            )

        self.assertEqual(direct_document_calls, [])
        mocked_document_drain.assert_called_once()
        self.assertEqual(
            mocked_document_drain.call_args.kwargs["database_url"],
            database_url,
        )
        self.assertEqual(
            mocked_document_drain.call_args.kwargs["document_limit"],
            3,
        )
        self.assertEqual(
            mocked_document_drain.call_args.kwargs["locked_by_prefix"],
            "scheduler-worker",
        )
        self.assertEqual(
            mocked_document_drain.call_args.kwargs["scheduler_run_id"],
            scheduler_run.scheduler_run_id,
        )
        self.assertEqual(stored_scheduler_run.selected_document_count, 7)
        self.assertEqual(stored_scheduler_run.completed_document_count, 6)
        self.assertEqual(stored_scheduler_run.failed_document_count, 1)
        self.assertEqual(stored_scheduler_run.status, "partial")
        self.assertEqual(stored_scheduler_run.error_message, "parse timeout")

    def test_processing_tick_wraps_document_drain_only(self) -> None:
        self.assertIsNotNone(run_processing_tick)
        sentinel_run = SimpleNamespace(
            scheduler_run_id="scheduler-run-x",
            trigger_type="processing",
            status="succeeded",
            started_at=None,
            finished_at=None,
            import_run_id=None,
            selected_document_count=2,
            completed_document_count=2,
            failed_document_count=0,
            error_message=None,
        )
        with mock.patch("newspaper_translator.document_processing.list_eligible_document_processing_runs", return_value=[SimpleNamespace(document_key="doc-1")]):
            with mock.patch("newspaper_translator.document_processing.create_scheduler_run", return_value=sentinel_run):
                with mock.patch("newspaper_translator.document_processing.finalize_scheduler_run"):
                    with mock.patch("newspaper_translator.document_processing.get_scheduler_run", return_value=sentinel_run):
                        with mock.patch("newspaper_translator.document_processing.run_document_processing_drain") as run_document_processing_drain:
                            with mock.patch("newspaper_translator.document_processing.run_article_processing_drain") as run_article_processing_drain:
                                run_document_processing_drain.return_value = DrainResult(
                                    did_work=True,
                                    selected_count=2,
                                    completed_count=2,
                                    failed_count=0,
                                )

                                result = run_processing_tick(
                                    database_url="sqlite:////tmp/newspaper-translator.db",
                                    trigger_type="processing",
                                    process_one_document=lambda **kwargs: None,
                                    document_limit=2,
                                )

        self.assertEqual(result.selected_document_count, 2)
        self.assertTrue(result.did_work)
        run_document_processing_drain.assert_called_once()
        run_article_processing_drain.assert_not_called()

    def test_scheduler_tick_continues_when_one_document_fails_and_marks_run_partial(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_scheduler_tick)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                "message-2:attachment-1:hash-2",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=first_document_key,
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=second_document_key,
            )

            processed_document_keys: list[str] = []

            def import_documents():
                return SimpleNamespace(run_id="import-run-1", created_document_count=0)

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                processed_document_keys.append(document_key)
                if document_key == first_document_key:
                    raise RuntimeError("parse timeout")
                return SimpleNamespace(
                    document_key=document_key,
                    status="succeeded",
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                )

            scheduler_run = run_scheduler_tick(
                database_url=database_url,
                trigger_type="interval",
                import_documents=import_documents,
                process_one_document=process_one_document,
                document_limit=10,
            )
            stored_scheduler_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=scheduler_run.scheduler_run_id,
            )

        self.assertEqual(processed_document_keys, [first_document_key, second_document_key])
        self.assertEqual(stored_scheduler_run.selected_document_count, 2)
        self.assertEqual(stored_scheduler_run.completed_document_count, 1)
        self.assertEqual(stored_scheduler_run.failed_document_count, 1)
        self.assertEqual(stored_scheduler_run.status, "partial")
        self.assertIn("parse timeout", stored_scheduler_run.error_message)

    def test_scheduler_tick_processes_multiple_documents_concurrently(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_scheduler_tick)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                "message-2:attachment-1:hash-2",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=first_document_key,
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=second_document_key,
            )

            active_count = 0
            max_active_count = 0
            active_lock = threading.Lock()
            concurrent_start = threading.Event()

            def import_documents():
                return SimpleNamespace(run_id="import-run-1", created_document_count=0)

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                nonlocal active_count, max_active_count
                with active_lock:
                    active_count += 1
                    max_active_count = max(max_active_count, active_count)
                    if active_count == 2:
                        concurrent_start.set()

                try:
                    if not concurrent_start.wait(timeout=1):
                        raise RuntimeError(f"document did not start concurrently: {document_key}")
                    return SimpleNamespace(
                        document_key=document_key,
                        status="succeeded",
                        scheduler_run_id=scheduler_run_id,
                        locked_by=locked_by,
                    )
                finally:
                    with active_lock:
                        active_count -= 1

            scheduler_run = run_scheduler_tick(
                database_url=database_url,
                trigger_type="interval",
                import_documents=import_documents,
                process_one_document=process_one_document,
                document_limit=2,
            )
            stored_scheduler_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=scheduler_run.scheduler_run_id,
            )

        self.assertEqual(max_active_count, 2)
        self.assertEqual(stored_scheduler_run.selected_document_count, 2)
        self.assertEqual(stored_scheduler_run.completed_document_count, 2)
        self.assertEqual(stored_scheduler_run.failed_document_count, 0)
        self.assertEqual(stored_scheduler_run.status, "succeeded")

    def test_scheduler_tick_emits_scheduler_and_import_lifecycle_logs(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_scheduler_tick)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            log_events: list[str] = []

            scheduler_run = run_scheduler_tick(
                database_url=database_url,
                trigger_type="interval",
                import_documents=lambda: SimpleNamespace(run_id="import-run-1"),
                process_one_document=lambda **kwargs: SimpleNamespace(status="succeeded"),
                document_limit=1,
                log_event=lambda *, event, details: log_events.append(event),
            )

        self.assertTrue(scheduler_run.did_work)
        self.assertEqual(
            log_events,
            [
                "scheduler.tick.started",
                "scheduler.import.started",
                "scheduler.import.finished",
                "scheduler.processing.started",
                "scheduler.processing.finished",
                "scheduler.tick.finished",
            ],
        )

    def test_processing_tick_skips_scheduler_run_when_no_eligible_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            scheduler_run = run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=lambda **_kw: SimpleNamespace(status="succeeded"),
                document_limit=4,
            )

            connection = sqlite3.connect(database_path)
            try:
                scheduler_run_count = connection.execute(
                    "SELECT COUNT(*) FROM scheduler_runs"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertFalse(scheduler_run.did_work)
        self.assertEqual(scheduler_run.scheduler_run_id, None)
        self.assertEqual(scheduler_run_count, 0)


if __name__ == "__main__":
    unittest.main()
