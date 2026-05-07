import pathlib
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
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
    from newspaper_translator.article_store import (
        create_parse_run,
        finalize_parse_run,
        get_latest_article_enrichment,
        list_latest_document_articles,
        record_parse_run_result,
    )
    from newspaper_translator.gemini import ArticleSummaryTagResult, ArticleTranslationResult
    from newspaper_translator.mineru import MineruParsedDocument
    from newspaper_translator.pdf import (
        ArticleFragment,
        ArticleSource,
        ParseMatchDecision,
        ParseResult,
        ParsedArticle,
    )
except ImportError:
    create_parse_run = None
    finalize_parse_run = None
    get_latest_article_enrichment = None
    list_latest_document_articles = None
    record_parse_run_result = None
    ArticleSummaryTagResult = None
    ArticleTranslationResult = None
    MineruParsedDocument = None
    ArticleFragment = None
    ArticleSource = None
    ParseMatchDecision = None
    ParseResult = None
    ParsedArticle = None

try:
    from newspaper_translator.document_processing import (
        claim_article_processing_run,
        claim_document_processing_run,
        create_article_processing_run,
        create_document_processing_run,
        create_scheduler_run,
        enqueue_document_article_processing_runs,
        enrich_document_articles,
        fail_article_processing_run,
        fail_document_processing_run,
        get_article_processing_run,
        get_document_processing_run,
        get_latest_scheduler_run,
        finalize_scheduler_run,
        get_scheduler_run,
        list_eligible_article_processing_runs,
        list_eligible_document_processing_runs,
        process_article_processing_run,
        process_document,
        ProcessingTickResult,
        recover_stale_article_runs,
        recover_stale_document_runs,
        request_manual_article_retry,
        run_processing_tick,
        run_document_processing_drain,
        run_scheduler_tick,
        succeed_article_processing_run,
        succeed_document_processing_run,
        request_manual_document_retry,
    )
except ImportError:
    claim_article_processing_run = None
    claim_document_processing_run = None
    create_article_processing_run = None
    create_document_processing_run = None
    create_scheduler_run = None
    enqueue_document_article_processing_runs = None
    enrich_document_articles = None
    fail_article_processing_run = None
    fail_document_processing_run = None
    finalize_scheduler_run = None
    get_article_processing_run = None
    get_document_processing_run = None
    get_latest_scheduler_run = None
    get_scheduler_run = None
    list_eligible_article_processing_runs = None
    list_eligible_document_processing_runs = None
    process_article_processing_run = None
    process_document = None
    ProcessingTickResult = None
    recover_stale_article_runs = None
    recover_stale_document_runs = None
    request_manual_article_retry = None
    run_processing_tick = None
    run_document_processing_drain = None
    run_scheduler_tick = None
    succeed_article_processing_run = None
    succeed_document_processing_run = None
    request_manual_document_retry = None


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
        self.assertEqual(created_run.current_step, "enrich")
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

    def test_process_document_retries_a_transient_parse_failure_without_counting_automatic_failure(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )

            parse_calls: list[str] = []
            enrich_calls: list[str] = []

            def flaky_parse(*, document_key: str) -> None:
                parse_calls.append(document_key)
                if len(parse_calls) == 1:
                    raise RuntimeError("mineru timeout")

            def enrich_document(*, document_key: str) -> None:
                enrich_calls.append(document_key)

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=flaky_parse,
                enrich_document=enrich_document,
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )

        self.assertEqual(parse_calls, [document_key, document_key])
        self.assertEqual(enrich_calls, [document_key])
        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual(stored_run.automatic_failure_count, 0)
        self.assertIsNone(stored_run.locked_by)
        self.assertIsNone(stored_run.lock_expires_at)

    def test_process_document_marks_failed_retryable_after_exhausted_parse_retries(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )

            parse_calls: list[str] = []
            enrich_calls: list[str] = []

            def failing_parse(*, document_key: str) -> None:
                parse_calls.append(document_key)
                raise RuntimeError("mineru timeout")

            def enrich_document(*, document_key: str) -> None:
                enrich_calls.append(document_key)

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=failing_parse,
                enrich_document=enrich_document,
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )

        self.assertEqual(parse_calls, [document_key, document_key, document_key])
        self.assertEqual(enrich_calls, [])
        self.assertEqual(stored_run.status, "failed_retryable")
        self.assertEqual(stored_run.current_step, "parse_persist")
        self.assertEqual(stored_run.automatic_failure_count, 1)
        self.assertEqual(stored_run.last_failure_step, "parse_persist")
        self.assertEqual(stored_run.last_error_message, "mineru timeout")

    def test_process_document_emits_step_retry_and_failure_lifecycle_logs(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )

            log_events: list[str] = []

            def failing_parse(*, document_key: str) -> None:
                raise RuntimeError("mineru timeout")

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=failing_parse,
                enrich_document=lambda **kwargs: None,
                step_retry_limit=1,
                lock_timeout_seconds=600,
                log_event=lambda *, event, details: log_events.append(event),
            )

        self.assertEqual(stored_run.status, "failed_retryable")
        self.assertEqual(
            log_events,
            [
                "document.claimed",
                "document.step.started",
                "document.step.retry_scheduled",
                "document.step.finished",
                "document.marked_failed",
            ],
        )

    def test_enrich_document_articles_enriches_latest_visible_articles_for_one_document(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(enrich_document_articles)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(get_latest_article_enrichment)

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

            latest_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            runs = enrich_document_articles(
                database_url=database_url,
                document_key=document_key,
                translator=_FakeTranslator(),
                summarizer_tagger=_FakeSummarizerTagger(),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )
            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=latest_articles[0].article_id,
            )

        self.assertEqual([run.article_id for run in runs], [latest_articles[0].article_id])
        self.assertEqual([run.status for run in runs], ["succeeded"])
        self.assertEqual(latest_enrichment.status, "succeeded")
        self.assertEqual(latest_enrichment.summary_status, "succeeded")
        self.assertEqual(latest_enrichment.tagging_status, "succeeded")

    def test_enrich_document_articles_continues_after_one_article_failure(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(enrich_document_articles)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(get_latest_article_enrichment)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            self._persist_multi_article_document_articles(
                database_url=database_url,
                document_key=document_key,
            )

            latest_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )

            with self.assertRaisesRegex(RuntimeError, "did not succeed"):
                enrich_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                    translator=_SelectiveFailingTranslator(
                        failing_titles={"First article title"},
                    ),
                    summarizer_tagger=_FakeSummarizerTagger(),
                    provider_name="gemini",
                    model_name="gemini-2.5-flash",
                    prompt_version="article-enrichment-v1",
                )

            second_article_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=latest_articles[1].article_id,
            )

        self.assertEqual(second_article_enrichment.status, "succeeded")

    def test_process_document_enqueues_article_processing_for_all_articles_without_failing_document(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
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

            def persist_parse_result(*, document_key: str) -> None:
                self._persist_multi_article_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=persist_parse_result,
                step_retry_limit=0,
                lock_timeout_seconds=600,
            )
            latest_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            article_runs = [
                get_article_processing_run(
                    database_url=database_url,
                    article_key=article.article_key,
                )
                for article in list_latest_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )
            ]

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual([run.article_id for run in article_runs], [article.article_id for article in latest_articles])
        self.assertEqual([run.status for run in article_runs], ["pending", "pending"])

    def test_process_document_can_enqueue_article_processing_from_real_parse_wiring(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
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

            def persist_parse_result(*, document_key: str) -> None:
                self._persist_parsed_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=persist_parse_result,
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )
            article = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0].article_id
            article_key = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0].article_key
            article_processing_run = get_article_processing_run(
                database_url=database_url,
                article_key=article_key,
            )

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual(article_processing_run.article_id, article)
        self.assertEqual(article_processing_run.status, "pending")

    def test_process_document_keeps_document_succeeded_when_article_enrichment_would_fail_later(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
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

            def persist_parse_result(*, document_key: str) -> None:
                self._persist_parsed_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=persist_parse_result,
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )
            article = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0]
            article_processing_run = get_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
            )

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual(stored_run.automatic_failure_count, 0)
        self.assertEqual(article_processing_run.article_id, article.article_id)
        self.assertEqual(article_processing_run.status, "pending")

    def test_process_document_can_use_real_parse_and_enqueue_article_processing_wiring(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(MineruParsedDocument)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            output_root = pathlib.Path(temp_dir) / "phase3-output"
            raw_pdf_path = pathlib.Path(temp_dir) / "wsj-2026-04-20.pdf"
            markdown_path = output_root / "wsj-2026-04-20" / "full.md"
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            raw_pdf_path.write_bytes(b"%PDF-1.4 sample")
            markdown_path.write_text(
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "The oil companies want to maximize their production.\n",
                encoding="utf-8",
            )
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
                raw_path=str(raw_pdf_path),
                original_filename="wsj-2026-04-20.pdf",
            )

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                parse_persist_document=None,
                output_root=output_root,
                mineru_client=_FakeMineruClient(
                    parsed_document=MineruParsedDocument(
                        batch_id="batch-1",
                        file_id="file-1",
                        file_name="wsj-2026-04-20.pdf",
                        markdown_path=markdown_path,
                        markdown_text=markdown_path.read_text(encoding="utf-8"),
                    )
                ),
                continuation_matcher=None,
                parser_name="mineru",
                parser_version="vlm",
                continuation_matcher_name="",
                continuation_matcher_version="",
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )
            article = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0]
            article_processing_run = get_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
            )

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual(article_processing_run.article_id, article.article_id)
        self.assertEqual(article_processing_run.status, "pending")

    def test_process_article_processing_run_succeeds_and_records_last_success_input_hash(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(process_article_processing_run)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(ArticleTranslationResult)
        self.assertIsNotNone(ArticleSummaryTagResult)

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
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )

            stored_run = process_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
                locked_by="article-worker-1",
                translator=lambda _article: ArticleTranslationResult(
                    content_type="article",
                    classification_reason="Regular newspaper article.",
                    translated_title_zh="标题",
                    translated_body_zh="正文",
                ),
                summarizer_tagger=lambda **kwargs: ArticleSummaryTagResult(
                    summary_zh="摘要",
                    tags=["能源", "市场", "国际"],
                ),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                lock_timeout_seconds=600,
            )
            connection = sqlite3.connect(database_path)
            try:
                latest_enrichment_row = connection.execute(
                    """
                    SELECT status, input_hash
                    FROM article_enrichment_runs
                    WHERE article_id = ?
                    ORDER BY started_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (article.article_id,),
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertIsNotNone(stored_run.last_success_input_hash)
        self.assertEqual(stored_run.last_success_input_hash, latest_enrichment_row[1])
        self.assertEqual(latest_enrichment_row[0], "succeeded")

    def test_enqueue_document_article_processing_runs_skips_unchanged_articles_and_requeues_changed_articles(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(enqueue_document_article_processing_runs)
        self.assertIsNotNone(process_article_processing_run)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(ArticleTranslationResult)
        self.assertIsNotNone(ArticleSummaryTagResult)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            self._persist_multi_article_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            first_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            initial_runs = enqueue_document_article_processing_runs(
                database_url=database_url,
                document_key=document_key,
            )
            for article in first_articles:
                process_article_processing_run(
                    database_url=database_url,
                    article_key=article.article_key,
                    locked_by=f"article-worker:{article.article_order}",
                    translator=lambda _article: ArticleTranslationResult(
                        content_type="article",
                        classification_reason="Regular newspaper article.",
                        translated_title_zh="标题",
                        translated_body_zh="正文",
                    ),
                    summarizer_tagger=lambda **kwargs: ArticleSummaryTagResult(
                        summary_zh="摘要",
                        tags=["能源", "市场", "国际"],
                    ),
                    provider_name="gemini",
                    model_name="gemini-2.5-flash",
                    prompt_version="article-enrichment-v2",
                    lock_timeout_seconds=600,
                )

            self._persist_custom_parse_result(
                database_url=database_url,
                document_key=document_key,
                parse_result=self._build_multi_article_parse_result(
                    first_body_text="First article body changed.",
                    second_body_text="Second article body.",
                ),
            )
            latest_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            refreshed_runs = enqueue_document_article_processing_runs(
                database_url=database_url,
                document_key=document_key,
            )
            runs_by_key = {
                article.article_key: get_article_processing_run(
                    database_url=database_url,
                    article_key=article.article_key,
                )
                for article in latest_articles
            }
            changed_article = next(article for article in latest_articles if article.title_en == "First article title")
            unchanged_article = next(article for article in latest_articles if article.title_en == "Second article title")

        self.assertEqual([run.status for run in initial_runs], ["pending", "pending"])
        self.assertEqual(
            [run.article_key for run in refreshed_runs],
            [changed_article.article_key],
        )
        self.assertEqual(runs_by_key[changed_article.article_key].article_id, changed_article.article_id)
        self.assertEqual(runs_by_key[changed_article.article_key].status, "pending")
        self.assertIsNotNone(runs_by_key[changed_article.article_key].last_success_input_hash)
        self.assertEqual(runs_by_key[unchanged_article.article_key].article_id, unchanged_article.article_id)
        self.assertEqual(runs_by_key[unchanged_article.article_key].status, "succeeded")
        self.assertIsNotNone(runs_by_key[unchanged_article.article_key].last_success_input_hash)

    def test_process_article_processing_run_respects_manual_retry_override_even_when_input_is_unchanged(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(process_article_processing_run)
        self.assertIsNotNone(request_manual_article_retry)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(ArticleTranslationResult)
        self.assertIsNotNone(ArticleSummaryTagResult)

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
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )
            translator_calls: list[str] = []

            def translator(_article):
                translator_calls.append("called")
                return ArticleTranslationResult(
                    content_type="article",
                    classification_reason="Regular newspaper article.",
                    translated_title_zh="标题",
                    translated_body_zh="正文",
                )

            summarizer = lambda **kwargs: ArticleSummaryTagResult(
                summary_zh="摘要",
                tags=["能源", "市场", "国际"],
            )

            first_run = process_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
                locked_by="article-worker-1",
                translator=translator,
                summarizer_tagger=summarizer,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                lock_timeout_seconds=600,
            )
            request_manual_article_retry(
                database_url=database_url,
                article_key=article.article_key,
            )
            second_run = process_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
                locked_by="article-worker-2",
                translator=translator,
                summarizer_tagger=summarizer,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                lock_timeout_seconds=600,
            )

        self.assertEqual(first_run.status, "succeeded")
        self.assertEqual(second_run.status, "succeeded")
        self.assertEqual(len(translator_calls), 2)

    def test_recover_stale_article_runs_marks_stale_running_articles_retryable_or_terminal(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(claim_article_processing_run)
        self.assertIsNotNone(recover_stale_article_runs)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            retryable_document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            terminal_document_key = self._insert_document(
                database_path,
                "message-2:attachment-1:hash-2",
            )
            fresh_document_key = self._insert_document(
                database_path,
                "message-3:attachment-1:hash-3",
            )

            for document_key in [
                retryable_document_key,
                terminal_document_key,
                fresh_document_key,
            ]:
                self._persist_parsed_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )
                article = list_latest_document_articles(
                    database_url=database_url,
                    document_key=document_key,
                )[0]
                create_article_processing_run(
                    database_url=database_url,
                    article_id=article.article_id,
                )
                claim_article_processing_run(
                    database_url=database_url,
                    article_key=article.article_key,
                    locked_by="article-worker-1",
                    lock_timeout_seconds=600,
                )

            retryable_article = list_latest_document_articles(
                database_url=database_url,
                document_key=retryable_document_key,
            )[0]
            terminal_article = list_latest_document_articles(
                database_url=database_url,
                document_key=terminal_document_key,
            )[0]
            fresh_article = list_latest_document_articles(
                database_url=database_url,
                document_key=fresh_document_key,
            )[0]
            self._set_article_processing_attempt_age_seconds(
                database_path=database_path,
                article_key=retryable_article.article_key,
                age_seconds=7200,
            )
            self._set_article_processing_attempt_age_seconds(
                database_path=database_path,
                article_key=terminal_article.article_key,
                age_seconds=7200,
                automatic_failure_count=1,
            )

            recovered_runs = recover_stale_article_runs(
                database_url=database_url,
                running_timeout_seconds=3600,
            )
            retryable_run = get_article_processing_run(
                database_url=database_url,
                article_key=retryable_article.article_key,
            )
            terminal_run = get_article_processing_run(
                database_url=database_url,
                article_key=terminal_article.article_key,
            )
            fresh_run = get_article_processing_run(
                database_url=database_url,
                article_key=fresh_article.article_key,
            )

        self.assertEqual(
            {run.article_key for run in recovered_runs},
            {retryable_article.article_key, terminal_article.article_key},
        )
        self.assertEqual(retryable_run.status, "failed_retryable")
        self.assertEqual(retryable_run.automatic_failure_count, 1)
        self.assertEqual(retryable_run.current_step, "enrich")
        self.assertIn("stale running timeout", retryable_run.last_error_message)
        self.assertEqual(terminal_run.status, "failed_terminal")
        self.assertEqual(terminal_run.automatic_failure_count, 2)
        self.assertEqual(fresh_run.status, "running")

    def test_recover_stale_document_runs_marks_stale_running_documents_retryable_or_terminal(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(recover_stale_document_runs)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            retryable_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            terminal_key = self._insert_document(
                database_path,
                "message-2:attachment-1:hash-2",
            )
            fresh_key = self._insert_document(
                database_path,
                "message-3:attachment-1:hash-3",
            )

            for key in [retryable_key, terminal_key, fresh_key]:
                create_document_processing_run(
                    database_url=database_url,
                    document_key=key,
                )
                claim_document_processing_run(
                    database_url=database_url,
                    document_key=key,
                    locked_by="worker-1",
                    lock_timeout_seconds=600,
                )

            self._set_document_processing_attempt_age_seconds(
                database_path=database_path,
                document_key=retryable_key,
                age_seconds=7200,
            )
            self._set_document_processing_attempt_age_seconds(
                database_path=database_path,
                document_key=terminal_key,
                age_seconds=7200,
                automatic_failure_count=1,
            )

            recovered_runs = recover_stale_document_runs(
                database_url=database_url,
                running_timeout_seconds=3600,
            )
            retryable_run = get_document_processing_run(
                database_url=database_url,
                document_key=retryable_key,
            )
            terminal_run = get_document_processing_run(
                database_url=database_url,
                document_key=terminal_key,
            )
            fresh_run = get_document_processing_run(
                database_url=database_url,
                document_key=fresh_key,
            )

        self.assertEqual(
            {run.document_key for run in recovered_runs},
            {retryable_key, terminal_key},
        )
        self.assertEqual(retryable_run.status, "failed_retryable")
        self.assertEqual(retryable_run.automatic_failure_count, 1)
        self.assertEqual(retryable_run.last_failure_step, "parse_persist")
        self.assertIn("stale running timeout", retryable_run.last_error_message)
        self.assertEqual(terminal_run.status, "failed_terminal")
        self.assertEqual(terminal_run.automatic_failure_count, 2)
        self.assertEqual(fresh_run.status, "running")

    def test_recover_stale_document_runs_emits_recovery_log_event(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(recover_stale_document_runs)

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
            self._set_document_processing_attempt_age_seconds(
                database_path=database_path,
                document_key=document_key,
                age_seconds=7200,
            )
            log_events: list[str] = []

            recover_stale_document_runs(
                database_url=database_url,
                running_timeout_seconds=3600,
                log_event=lambda *, event, details: log_events.append(f"{event}:{details['document_key']}"),
            )

        self.assertEqual(log_events, [f"document.recovered_stale:{document_key}"])

    def test_scheduler_tick_processes_pending_article_runs(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(run_scheduler_tick)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(succeed_article_processing_run)

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
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )
            processed_article_keys: list[str] = []

            def process_one_article(*, article_key: str, locked_by: str):
                processed_article_keys.append(article_key)
                return succeed_article_processing_run(
                    database_url=database_url,
                    article_key=article_key,
                    last_success_input_hash=f"hash:{locked_by}",
                )

            scheduler_run = run_scheduler_tick(
                database_url=database_url,
                trigger_type="interval",
                import_documents=lambda: SimpleNamespace(run_id="import-run-1"),
                process_one_document=lambda **kwargs: SimpleNamespace(status="succeeded"),
                document_limit=10,
                process_one_article=process_one_article,
                article_limit=10,
            )
            stored_run = get_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
            )

        self.assertTrue(scheduler_run.did_work)
        self.assertEqual(processed_article_keys, [article.article_key])
        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.last_success_input_hash, "hash:article-worker-1")

    def test_scheduler_tick_marks_run_partial_when_article_processing_fails(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(run_scheduler_tick)
        self.assertIsNotNone(get_scheduler_run)
        self.assertIsNotNone(list_latest_document_articles)

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
            self._persist_parsed_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            article = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0]
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )

            scheduler_run = run_scheduler_tick(
                database_url=database_url,
                trigger_type="interval",
                import_documents=lambda: SimpleNamespace(run_id="import-run-1"),
                process_one_document=lambda **kwargs: SimpleNamespace(status="succeeded"),
                document_limit=10,
                process_one_article=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("article gemini timeout")),
                article_limit=10,
            )
            stored_scheduler_run = get_scheduler_run(
                database_url=database_url,
                scheduler_run_id=scheduler_run.scheduler_run_id,
            )

        self.assertEqual(stored_scheduler_run.status, "partial")
        self.assertEqual(stored_scheduler_run.completed_document_count, 1)
        self.assertEqual(stored_scheduler_run.failed_document_count, 1)
        self.assertIn("article gemini timeout", stored_scheduler_run.error_message)

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

    def test_processing_tick_processes_documents_before_articles(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(run_processing_tick)
        self.assertIsNotNone(list_latest_document_articles)

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
            self._persist_parsed_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            article = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0]
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )
            events: list[str] = []

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                events.append(f"document:{document_key}")
                return SimpleNamespace(status="succeeded")

            def process_one_article(*, article_key: str, locked_by: str):
                events.append(f"article:{article_key}")
                return succeed_article_processing_run(
                    database_url=database_url,
                    article_key=article_key,
                    last_success_input_hash=f"hash:{locked_by}",
                )

            run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=process_one_document,
                document_limit=10,
                process_one_article=process_one_article,
                article_limit=10,
            )

        self.assertEqual(events, [f"document:{document_key}", f"article:{article.article_key}"])

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

    def test_document_processing_drain_refills_free_slots_until_queue_is_empty(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_document_processing_drain)
        self.assertIsNotNone(get_document_processing_run)
        self.assertIsNotNone(process_document)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_keys = [
                self._insert_document(
                    database_path,
                    f"message-{index}:attachment-1:hash-{index}",
                )
                for index in range(1, 6)
            ]
            for document_key in document_keys:
                create_document_processing_run(
                    database_url=database_url,
                    document_key=document_key,
                )

            in_flight: list[str] = []
            processed: list[str] = []
            peak_in_flight = 0
            lock = threading.Lock()

            def parse_persist_document(*, document_key: str):
                nonlocal peak_in_flight
                with lock:
                    in_flight.append(document_key)
                    peak_in_flight = max(peak_in_flight, len(in_flight))
                try:
                    time.sleep(0.05)
                    processed.append(document_key)
                    return None
                finally:
                    with lock:
                        in_flight.remove(document_key)

            def enrich_document(*, document_key: str):
                return None

            drain_result = run_document_processing_drain(
                database_url=database_url,
                process_one_document=lambda **kwargs: process_document(
                    database_url=database_url,
                    parse_persist_document=parse_persist_document,
                    enrich_document=enrich_document,
                    **kwargs,
                ),
                document_limit=2,
                scheduler_run_id="scheduler-run-1",
            )
            stored_runs = [
                get_document_processing_run(
                    database_url=database_url,
                    document_key=document_key,
                )
                for document_key in document_keys
            ]

        self.assertCountEqual(processed, document_keys)
        self.assertLessEqual(peak_in_flight, 2)
        self.assertTrue(drain_result.did_work)
        self.assertEqual(drain_result.selected_count, 5)
        self.assertEqual(drain_result.completed_count, 5)
        self.assertEqual(drain_result.failed_count, 0)
        self.assertEqual(drain_result.error_messages, ())
        self.assertEqual(
            [stored_run.status for stored_run in stored_runs],
            ["succeeded"] * 5,
        )

    def test_document_processing_drain_continues_after_one_task_failure(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_document_processing_drain)
        self.assertIsNotNone(get_document_processing_run)
        self.assertIsNotNone(process_document)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_keys = [
                self._insert_document(
                    database_path,
                    f"message-{index}:attachment-1:hash-{index}",
                )
                for index in range(1, 4)
            ]
            for document_key in document_keys:
                create_document_processing_run(
                    database_url=database_url,
                    document_key=document_key,
                )
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """
                    UPDATE document_processing_runs
                    SET automatic_failure_count = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE document_key = ?
                    """,
                    (document_keys[1],),
                )
                connection.commit()
            finally:
                connection.close()

            processed: list[str] = []

            def parse_persist_document(*, document_key: str):
                processed.append(document_key)
                if document_key == document_keys[1]:
                    raise RuntimeError("parse timeout")
                return None

            def enrich_document(*, document_key: str):
                return None

            drain_result = run_document_processing_drain(
                database_url=database_url,
                process_one_document=lambda **kwargs: process_document(
                    database_url=database_url,
                    parse_persist_document=parse_persist_document,
                    enrich_document=enrich_document,
                    step_retry_limit=0,
                    **kwargs,
                ),
                document_limit=2,
                scheduler_run_id="scheduler-run-1",
            )
            stored_runs = {
                document_key: get_document_processing_run(
                    database_url=database_url,
                    document_key=document_key,
                )
                for document_key in document_keys
            }

        self.assertCountEqual(processed, document_keys)
        self.assertTrue(drain_result.did_work)
        self.assertEqual(drain_result.selected_count, 3)
        self.assertEqual(drain_result.completed_count, 2)
        self.assertEqual(drain_result.failed_count, 1)
        self.assertEqual(stored_runs[document_keys[1]].status, "failed_terminal")
        self.assertEqual(stored_runs[document_keys[1]].last_error_message, "parse timeout")
        self.assertEqual(stored_runs[document_keys[0]].status, "succeeded")
        self.assertEqual(stored_runs[document_keys[2]].status, "succeeded")

    def test_document_processing_drain_skips_contended_claim_without_counting_failure(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_document_processing_drain)
        self.assertIsNotNone(get_document_processing_run)
        self.assertIsNotNone(process_document)
        self.assertIsNotNone(claim_document_processing_run)

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

            processed: list[str] = []

            def parse_persist_document(*, document_key: str):
                processed.append(document_key)
                return None

            def enrich_document(*, document_key: str):
                return None

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                if document_key == second_document_key:
                    claim_document_processing_run(
                        database_url=database_url,
                        document_key=document_key,
                        locked_by="other-worker",
                        lock_timeout_seconds=600,
                        scheduler_run_id="other-scheduler-run",
                    )
                return process_document(
                    database_url=database_url,
                    document_key=document_key,
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                    parse_persist_document=parse_persist_document,
                    enrich_document=enrich_document,
                )

            drain_result = run_document_processing_drain(
                database_url=database_url,
                process_one_document=process_one_document,
                document_limit=2,
                scheduler_run_id="scheduler-run-1",
            )
            first_stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=first_document_key,
            )
            second_stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=second_document_key,
            )

        self.assertEqual(processed, [first_document_key])
        self.assertTrue(drain_result.did_work)
        self.assertEqual(drain_result.selected_count, 2)
        self.assertEqual(drain_result.completed_count, 1)
        self.assertEqual(drain_result.failed_count, 0)
        self.assertEqual(drain_result.error_messages, ())
        self.assertEqual(first_stored_run.status, "succeeded")
        self.assertEqual(second_stored_run.status, "running")
        self.assertEqual(second_stored_run.locked_by, "other-worker")

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

    def _insert_document(
        self,
        database_path: pathlib.Path,
        document_key: str,
        *,
        raw_path: str = "/tmp/wsj-2026-04-20.pdf",
        original_filename: str = "wsj-2026-04-20.pdf",
    ) -> str:
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
                    original_filename,
                    document_key.split(":")[-1],
                    raw_path,
                    "imported",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key

    def _persist_parsed_document_articles(
        self,
        *,
        database_url: str,
        document_key: str,
        article_count: int = 1,
    ) -> None:
        if article_count == 1:
            parse_result = self._build_parse_result()
        elif article_count == 2:
            parse_result = self._build_multi_article_parse_result()
        else:
            parse_result = self._build_n_article_parse_result(article_count)
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date="2026-04-20",
            continuation_matcher_name="gemini",
            continuation_matcher_version="2.5-flash",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=parse_result,
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )

    def _persist_multi_article_document_articles(
        self,
        *,
        database_url: str,
        document_key: str,
    ) -> None:
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date="2026-04-20",
            continuation_matcher_name="gemini",
            continuation_matcher_version="2.5-flash",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=self._build_multi_article_parse_result(),
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )

    def _persist_custom_parse_result(
        self,
        *,
        database_url: str,
        document_key: str,
        parse_result: ParseResult,
    ) -> None:
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date="2026-04-20",
            continuation_matcher_name="gemini",
            continuation_matcher_version="2.5-flash",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=parse_result,
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )

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

    def _set_document_processing_attempt_age_seconds(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        age_seconds: int,
        automatic_failure_count: int | None = None,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            if automatic_failure_count is None:
                connection.execute(
                    """
                    UPDATE document_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE document_key = ?
                    """,
                    (age_seconds, document_key),
                )
            else:
                connection.execute(
                    """
                    UPDATE document_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        automatic_failure_count = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE document_key = ?
                    """,
                    (age_seconds, automatic_failure_count, document_key),
                )
            connection.commit()
        finally:
            connection.close()

    def _set_article_processing_attempt_age_seconds(
        self,
        *,
        database_path: pathlib.Path,
        article_key: str,
        age_seconds: int,
        automatic_failure_count: int | None = None,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            if automatic_failure_count is None:
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (age_seconds, article_key),
                )
            else:
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        automatic_failure_count = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (age_seconds, automatic_failure_count, article_key),
                )
            connection.commit()
        finally:
            connection.close()

    def _set_scheduler_run_started_at(
        self,
        *,
        database_path: pathlib.Path,
        scheduler_run_id: str,
        started_at: str,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                UPDATE scheduler_runs
                SET started_at = ?
                WHERE scheduler_run_id = ?
                """,
                (started_at, scheduler_run_id),
            )
            connection.commit()
        finally:
            connection.close()

    def _build_n_article_parse_result(self, n: int) -> "ParseResult":
        from newspaper_translator.pdf import ArticleFragment, ArticleSource, ParseMatchDecision, ParsedArticle, ParseResult
        fragments = [
            ArticleFragment(
                title=f"Article {i} title",
                body_text=f"Article {i} body.",
                source_order=i,
                continued_to_page="",
                continued_from_page="",
            )
            for i in range(1, n + 1)
        ]
        articles = [
            ParsedArticle(
                article_order=i,
                primary_source_order=i,
                source_fragment_count=1,
                title=f"Article {i} title",
                body_text=f"Article {i} body.",
                source_fragments=[
                    ArticleSource(
                        source_order=i,
                        fragment_role="single",
                        sequence_index=1,
                    )
                ],
            )
            for i in range(1, n + 1)
        ]
        return ParseResult(fragments=fragments, match_decisions=[], articles=articles)

    def test_article_tick_runs_batch_size_with_bounded_concurrency(self) -> None:
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
            self._persist_parsed_document_articles(
                database_url=database_url,
                document_key=document_key,
                article_count=8,
            )
            for article in list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            ):
                create_article_processing_run(
                    database_url=database_url,
                    article_id=article.article_id,
                )

            in_flight: list[int] = []
            in_flight_lock = threading.Lock()
            peak_in_flight = 0
            processed: list[str] = []

            def process_one_document(*, document_key, scheduler_run_id, locked_by):
                return SimpleNamespace(status="succeeded")

            def process_one_article(*, article_key, locked_by):
                nonlocal peak_in_flight
                with in_flight_lock:
                    in_flight.append(article_key)
                    peak_in_flight = max(peak_in_flight, len(in_flight))
                try:
                    time.sleep(0.05)
                    return succeed_article_processing_run(
                        database_url=database_url,
                        article_key=article_key,
                        last_success_input_hash="hash-x",
                    )
                finally:
                    with in_flight_lock:
                        in_flight.remove(article_key)
                        processed.append(article_key)

            scheduler_run = run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=process_one_document,
                document_limit=2,
                process_one_article=process_one_article,
                article_limit=4,
                article_batch_size=8,
            )

        self.assertEqual(len(processed), 8)
        self.assertLessEqual(peak_in_flight, 4)
        self.assertEqual(scheduler_run.selected_document_count, 1 + 8)
        self.assertTrue(scheduler_run.did_work)

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
                process_one_article=lambda **_kw: SimpleNamespace(status="succeeded"),
                article_limit=4,
                article_batch_size=8,
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

    def _build_parse_result(self) -> ParseResult:
        return ParseResult(
            fragments=[
                ArticleFragment(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="U.S. oil futures were trading near $90 a barrel Sunday.",
                    source_order=1,
                    continued_to_page="",
                    continued_from_page="",
                )
            ],
            match_decisions=[
                ParseMatchDecision(
                    front_source_order=None,
                    back_source_order=None,
                    decision_status="skipped",
                    decision_reason="single fragment article",
                    matcher_raw_response="[]",
                )
            ],
            articles=[
                ParsedArticle(
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=1,
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="The oil companies want to maximize their production.",
                    source_fragments=[
                        ArticleSource(
                            source_order=1,
                            fragment_role="single",
                            sequence_index=1,
                        )
                    ],
                )
            ],
        )

    def _build_multi_article_parse_result(
        self,
        *,
        first_body_text: str = "First article body.",
        second_body_text: str = "Second article body.",
    ) -> ParseResult:
        return ParseResult(
            fragments=[
                ArticleFragment(
                    title="First article title",
                    body_text=first_body_text,
                    source_order=1,
                    continued_to_page="",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Second article title",
                    body_text=second_body_text,
                    source_order=2,
                    continued_to_page="",
                    continued_from_page="",
                ),
            ],
            match_decisions=[],
            articles=[
                ParsedArticle(
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=1,
                    title="First article title",
                    body_text=first_body_text,
                    source_fragments=[
                        ArticleSource(
                            source_order=1,
                            fragment_role="single",
                            sequence_index=1,
                        )
                    ],
                ),
                ParsedArticle(
                    article_order=2,
                    primary_source_order=2,
                    source_fragment_count=1,
                    title="Second article title",
                    body_text=second_body_text,
                    source_fragments=[
                        ArticleSource(
                            source_order=2,
                            fragment_role="single",
                            sequence_index=1,
                        )
                    ],
                ),
            ],
        )


class _FakeTranslator:
    def __call__(self, article):
        return ArticleTranslationResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
        )


class _SelectiveFailingTranslator:
    def __init__(self, *, failing_titles: set[str]) -> None:
        self._failing_titles = failing_titles

    def __call__(self, article):
        if article.title_en in self._failing_titles:
            raise RuntimeError("translation timeout")
        return ArticleTranslationResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translated_title_zh=f"{article.title_en} 中文",
            translated_body_zh=f"{article.body_text_en} 中文",
        )


class _FakeSummarizerTagger:
    def __call__(self, *, article, translated_title_zh: str, translated_body_zh: str):
        return ArticleSummaryTagResult(
            summary_zh="油企为避开中东风险，正把勘探重点转向非洲和南美。",
            tags=["能源", "石油", "中东局势"],
        )


class _FailingSummarizerTagger:
    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, *, article, translated_title_zh: str, translated_body_zh: str):
        raise RuntimeError(self._message)


class _FakeMineruClient:
    def __init__(self, *, parsed_document) -> None:
        self._parsed_document = parsed_document

    def parse_pdf(self, *, pdf_path: pathlib.Path, output_root: pathlib.Path):
        return self._parsed_document


if __name__ == "__main__":
    unittest.main()
