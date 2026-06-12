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
    create_document_processing_run,
    claim_document_processing_run,
    get_document_processing_run,
    list_eligible_document_processing_runs,
    list_document_processing_runs,
    get_document_processing_max_failure_count,
    fail_document_processing_run,
    request_manual_document_retry,
    create_article_processing_run,
    claim_article_processing_run,
    get_article_processing_run,
    list_eligible_article_processing_runs,
    request_manual_article_retry,
    fail_article_processing_run,
    succeed_article_processing_run,
    list_latest_document_articles,
)


class DocumentRunStoreTests(DocumentProcessingTestMixin, unittest.TestCase):
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

    def test_marks_document_failed_retryable_after_first_automatic_failure(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(fail_document_processing_run)

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
            claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                failed_step="parse_persist",
                error_message="mineru timeout",
            )
            stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(stored_run.status, "failed_retryable")
        self.assertEqual(stored_run.automatic_failure_count, 1)
        self.assertEqual(stored_run.last_failure_step, "parse_persist")
        self.assertEqual(stored_run.last_error_message, "mineru timeout")
        self.assertIsNone(stored_run.locked_by)
        self.assertIsNone(stored_run.lock_expires_at)
        self.assertIsNotNone(stored_run.last_attempt_finished_at)

    def test_marks_document_failed_retryable_and_emits_failure_log(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(fail_document_processing_run)

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
            claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            log_events: list[str] = []

            stored_run = fail_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                failed_step="parse_persist",
                error_message="mineru timeout",
                log_event=lambda *, event, details: log_events.append(f"{event}:{details['status']}"),
            )

        self.assertEqual(stored_run.status, "failed_retryable")
        self.assertEqual(log_events, ["document.marked_failed:failed_retryable"])

    def test_marks_document_failed_terminal_after_second_automatic_failure(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(fail_document_processing_run)

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
            claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                failed_step="parse_persist",
                error_message="mineru timeout",
            )
            claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                failed_step="enrich",
                error_message="gemini timeout",
            )
            stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(stored_run.status, "failed_terminal")
        self.assertEqual(stored_run.automatic_failure_count, 2)
        self.assertEqual(stored_run.last_failure_step, "enrich")
        self.assertEqual(stored_run.last_error_message, "gemini timeout")
        self.assertIsNone(stored_run.locked_by)
        self.assertIsNone(stored_run.lock_expires_at)

    def test_manual_retry_reactivates_a_terminal_document(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(fail_document_processing_run)
        self.assertIsNotNone(request_manual_document_retry)

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
            claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                failed_step="parse_persist",
                error_message="mineru timeout",
            )
            claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                failed_step="enrich",
                error_message="gemini timeout",
            )
            request_manual_document_retry(
                database_url=database_url,
                document_key=document_key,
            )
            stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(stored_run.status, "manual_retry_requested")
        self.assertEqual(stored_run.automatic_failure_count, 2)
        self.assertEqual(stored_run.last_failure_step, "enrich")
        self.assertEqual(stored_run.last_error_message, "gemini timeout")
        self.assertIsNone(stored_run.locked_by)
        self.assertIsNone(stored_run.lock_expires_at)

    def test_manual_retry_emits_log_event(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(request_manual_document_retry)

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

            stored_run = request_manual_document_retry(
                database_url=database_url,
                document_key=document_key,
                log_event=lambda *, event, details: log_events.append(f"{event}:{details['document_key']}"),
            )

        self.assertEqual(stored_run.status, "manual_retry_requested")
        self.assertEqual(log_events, [f"document.manual_retry_requested:{document_key}"])

    def test_lists_document_processing_runs_filtered_by_min_failure_count(self) -> None:
        self.assertIsNotNone(list_document_processing_runs)
        self.assertIsNotNone(get_document_processing_max_failure_count)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            create_document_processing_run(database_url=database_url, document_key="doc-zero")
            create_document_processing_run(database_url=database_url, document_key="doc-one")
            create_document_processing_run(database_url=database_url, document_key="doc-two")
            # doc-one: 1 failure (failed_retryable)
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-one",
                failed_step="parse_persist",
                error_message="boom",
            )
            # doc-two: 2 failures (failed_terminal)
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )

            at_least_one = list_document_processing_runs(
                database_url=database_url,
                limit=50,
                min_failure_count=1,
            )
            at_least_two = list_document_processing_runs(
                database_url=database_url,
                limit=50,
                min_failure_count=2,
            )
            with_status = list_document_processing_runs(
                database_url=database_url,
                limit=50,
                status="failed_retryable",
                min_failure_count=1,
            )

        self.assertEqual({run.document_key for run in at_least_one}, {"doc-one", "doc-two"})
        self.assertEqual({run.document_key for run in at_least_two}, {"doc-two"})
        self.assertEqual({run.document_key for run in with_status}, {"doc-one"})

    def test_document_processing_max_failure_count_returns_global_max(self) -> None:
        self.assertIsNotNone(get_document_processing_max_failure_count)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            self.assertEqual(
                get_document_processing_max_failure_count(database_url=database_url),
                0,
            )

            create_document_processing_run(database_url=database_url, document_key="doc-two")
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )

            self.assertEqual(
                get_document_processing_max_failure_count(database_url=database_url),
                2,
            )

    def test_claims_one_eligible_article_processing_run_without_double_claim(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(claim_article_processing_run)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            self._persist_parsed_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            article = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0]

            created_run = create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )
            claimed_run = claim_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            second_claim = claim_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
                locked_by="worker-2",
                lock_timeout_seconds=600,
            )
            stored_run = get_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
            )

        self.assertEqual(created_run.status, "pending")
        self.assertEqual(created_run.current_step, "await_ad_judgment")
        self.assertIsNotNone(claimed_run)
        self.assertEqual(claimed_run.status, "running")
        self.assertEqual(claimed_run.locked_by, "worker-1")
        self.assertIsNone(second_claim)
        self.assertEqual(stored_run.status, "running")
        self.assertEqual(stored_run.locked_by, "worker-1")

    def test_lists_eligible_article_processing_runs_with_manual_retry_priority(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(list_eligible_article_processing_runs)
        self.assertIsNotNone(request_manual_article_retry)
        self.assertIsNotNone(fail_article_processing_run)
        self.assertIsNotNone(claim_article_processing_run)
        self.assertIsNotNone(succeed_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            manual_retry_key = self._insert_document(database_path, "message-1:attachment-1:hash-1")
            pending_key = self._insert_document(database_path, "message-2:attachment-1:hash-2")
            retryable_key = self._insert_document(database_path, "message-3:attachment-1:hash-3")
            running_key = self._insert_document(database_path, "message-4:attachment-1:hash-4")
            succeeded_key = self._insert_document(database_path, "message-5:attachment-1:hash-5")

            for document_key in [
                manual_retry_key,
                pending_key,
                retryable_key,
                running_key,
                succeeded_key,
            ]:
                self._persist_parsed_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )

            manual_retry_article = list_latest_document_articles(database_url=database_url, document_key=manual_retry_key)[0]
            pending_article = list_latest_document_articles(database_url=database_url, document_key=pending_key)[0]
            retryable_article = list_latest_document_articles(database_url=database_url, document_key=retryable_key)[0]
            running_article = list_latest_document_articles(database_url=database_url, document_key=running_key)[0]
            succeeded_article = list_latest_document_articles(database_url=database_url, document_key=succeeded_key)[0]

            for article in [
                manual_retry_article,
                pending_article,
                retryable_article,
                running_article,
                succeeded_article,
            ]:
                create_article_processing_run(
                    database_url=database_url,
                    article_id=article.article_id,
                )

            request_manual_article_retry(
                database_url=database_url,
                article_key=manual_retry_article.article_key,
            )
            claim_article_processing_run(
                database_url=database_url,
                article_key=retryable_article.article_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            fail_article_processing_run(
                database_url=database_url,
                article_key=retryable_article.article_key,
                failed_step="enrich",
                error_message="gemini timeout",
            )
            claim_article_processing_run(
                database_url=database_url,
                article_key=running_article.article_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
            )
            succeed_article_processing_run(
                database_url=database_url,
                article_key=succeeded_article.article_key,
                last_success_input_hash="hash-1",
            )

            eligible_runs = list_eligible_article_processing_runs(
                database_url=database_url,
                limit=10,
            )

        self.assertEqual(
            [run.article_key for run in eligible_runs],
            [
                manual_retry_article.article_key,
                pending_article.article_key,
                retryable_article.article_key,
            ],
        )


if __name__ == "__main__":
    unittest.main()
