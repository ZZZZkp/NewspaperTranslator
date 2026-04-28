import pathlib
import sqlite3
import sys
import tempfile
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
        claim_document_processing_run,
        create_document_processing_run,
        create_scheduler_run,
        enrich_document_articles,
        fail_document_processing_run,
        get_document_processing_run,
        finalize_scheduler_run,
        get_scheduler_run,
        list_eligible_document_processing_runs,
        process_document,
        recover_stale_document_runs,
        run_scheduler_tick,
        request_manual_document_retry,
    )
except ImportError:
    claim_document_processing_run = None
    create_document_processing_run = None
    create_scheduler_run = None
    enrich_document_articles = None
    fail_document_processing_run = None
    finalize_scheduler_run = None
    get_document_processing_run = None
    get_scheduler_run = None
    list_eligible_document_processing_runs = None
    process_document = None
    recover_stale_document_runs = None
    run_scheduler_tick = None
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

    def test_process_document_can_use_real_document_level_enrichment_wiring(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
        self.assertIsNotNone(get_latest_article_enrichment)

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
                translator=_FakeTranslator(),
                summarizer_tagger=_FakeSummarizerTagger(),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )
            article_id = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0].article_id
            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article_id,
            )

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual(latest_enrichment.status, "succeeded")

    def test_process_document_marks_failed_retryable_when_document_level_enrichment_never_succeeds(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
        self.assertIsNotNone(get_latest_article_enrichment)

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
                translator=_FakeTranslator(),
                summarizer_tagger=_FailingSummarizerTagger("summary timeout"),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )
            article_id = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0].article_id
            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article_id,
            )

        self.assertEqual(stored_run.status, "failed_retryable")
        self.assertEqual(stored_run.current_step, "enrich")
        self.assertEqual(stored_run.automatic_failure_count, 1)
        self.assertEqual(stored_run.last_failure_step, "enrich")
        self.assertIn("did not succeed", stored_run.last_error_message)
        self.assertEqual(latest_enrichment.status, "partial")

    def test_process_document_can_use_real_parse_and_enrichment_wiring(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(process_document)
        self.assertIsNotNone(get_latest_article_enrichment)
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
                translator=_FakeTranslator(),
                summarizer_tagger=_FakeSummarizerTagger(),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
                step_retry_limit=2,
                lock_timeout_seconds=600,
            )
            article_id = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )[0].article_id
            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article_id,
            )

        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
        self.assertEqual(latest_enrichment.status, "succeeded")

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
            parse_result=self._build_parse_result(),
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


class _FakeTranslator:
    def __call__(self, article):
        return ArticleTranslationResult(
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
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
