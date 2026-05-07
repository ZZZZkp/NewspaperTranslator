import pathlib
import sqlite3
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
    _FakeTranslator,
    _FakeSummarizerTagger,
    _FailingSummarizerTagger,
    run_pending_migrations,
    create_article_processing_run,
    claim_article_processing_run,
    process_article_processing_run,
    get_article_processing_run,
    list_latest_document_articles,
    request_manual_article_retry,
    enqueue_document_article_processing_runs,
    recover_stale_article_runs,
    recover_stale_document_runs,
    create_document_processing_run,
    claim_document_processing_run,
    get_document_processing_run,
    ArticleTranslationResult,
    ArticleSummaryTagResult,
)


class ProcessArticleTests(DocumentProcessingTestMixin, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
