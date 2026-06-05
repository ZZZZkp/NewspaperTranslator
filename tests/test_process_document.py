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
    _FakeTranslator,
    _SelectiveFailingTranslator,
    _FakeSummarizerTagger,
    _FailingSummarizerTagger,
    _FakeMineruClient,
    run_pending_migrations,
    create_document_processing_run,
    claim_document_processing_run,
    process_document,
    enrich_document_articles,
    get_article_processing_run,
    list_latest_document_articles,
    get_latest_article_enrichment,
    MineruParsedDocument,
    MineruParsedPage,
)


class ProcessDocumentTests(DocumentProcessingTestMixin, unittest.TestCase):
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

    def test_process_document_uses_explicit_preclaimed_run_without_reclaiming(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(process_document)

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
            preclaimed_run = claim_document_processing_run(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                lock_timeout_seconds=600,
                scheduler_run_id="scheduler-run-1",
            )
            parse_calls: list[str] = []
            enrich_calls: list[str] = []

            def parse_persist_document(*, document_key: str) -> None:
                parse_calls.append(document_key)

            def enrich_document(*, document_key: str) -> None:
                enrich_calls.append(document_key)

            stored_run = process_document(
                database_url=database_url,
                document_key=document_key,
                locked_by="worker-1",
                scheduler_run_id="scheduler-run-1",
                preclaimed_run=preclaimed_run,
                parse_persist_document=parse_persist_document,
                enrich_document=enrich_document,
            )

        self.assertEqual(parse_calls, [document_key])
        self.assertEqual(enrich_calls, [document_key])
        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(stored_run.current_step, "completed")
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
                        pages=(
                            MineruParsedPage(
                                page_number=1,
                                batch_id="batch-1",
                                file_id="page-0001",
                                file_name="page-0001.pdf",
                                markdown_path=output_root / "page-0001.md",
                                markdown_text=markdown_path.read_text(encoding="utf-8"),
                            ),
                        ),
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


if __name__ == "__main__":
    unittest.main()
