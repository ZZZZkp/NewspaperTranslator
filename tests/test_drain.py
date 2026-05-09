import pathlib
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
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
    _FakeTranslator,
    _FakeSummarizerTagger,
    create_scheduler_run,
    run_pending_migrations,
    document_processing_module,
    create_document_processing_run,
    claim_document_processing_run,
    get_document_processing_run,
    run_document_processing_drain,
    run_processing_tick,
    process_document,
    create_article_processing_run,
    claim_article_processing_run,
    get_article_processing_run,
    run_article_processing_drain,
    process_article_processing_run,
    list_latest_document_articles,
    request_manual_article_retry,
    ArticleTranslationResult,
    ArticleSummaryTagResult,
)


class DrainTests(DocumentProcessingTestMixin, unittest.TestCase):
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

    def test_document_processing_drain_skips_contended_claim_before_submit(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_document_processing_drain)
        self.assertIsNotNone(get_document_processing_run)
        self.assertIsNotNone(process_document)
        self.assertIsNotNone(claim_document_processing_run)
        self.assertIsNotNone(document_processing_module)

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
            original_claim_document_processing_run = claim_document_processing_run

            def contend_second_claim(**kwargs):
                if kwargs["document_key"] == second_document_key:
                    original_claim_document_processing_run(
                        database_url=database_url,
                        document_key=second_document_key,
                        locked_by="other-worker",
                        lock_timeout_seconds=600,
                        scheduler_run_id="other-scheduler-run",
                    )
                return original_claim_document_processing_run(**kwargs)

            def parse_persist_document(*, document_key: str):
                processed.append(document_key)
                return None

            def enrich_document(*, document_key: str):
                return None

            def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
                return process_document(
                    database_url=database_url,
                    document_key=document_key,
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                    parse_persist_document=parse_persist_document,
                    enrich_document=enrich_document,
                )

            with mock.patch.object(
                document_processing_module,
                "claim_document_processing_run",
                side_effect=contend_second_claim,
            ):
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
        self.assertEqual(drain_result.selected_count, 1)
        self.assertEqual(drain_result.completed_count, 1)
        self.assertEqual(drain_result.failed_count, 0)
        self.assertEqual(drain_result.error_messages, ())
        self.assertEqual(first_stored_run.status, "succeeded")
        self.assertEqual(second_stored_run.status, "running")
        self.assertEqual(second_stored_run.locked_by, "other-worker")

    def test_document_processing_drain_retries_transient_database_lock_when_listing_runs(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(run_document_processing_drain)
        self.assertIsNotNone(get_document_processing_run)
        self.assertIsNotNone(process_document)
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

            processed: list[str] = []
            list_attempts = 0

            class RetryOnceListConnection:
                def __init__(self, connection):
                    self._connection = connection

                def execute(self, sql, parameters=()):
                    nonlocal list_attempts
                    if "FROM document_processing_runs" in sql and "WHERE status IN ('manual_retry_requested', 'pending', 'failed_retryable')" in sql:
                        list_attempts += 1
                        if list_attempts == 1:
                            raise sqlite3.OperationalError("database is locked")
                    return self._connection.execute(sql, parameters)

                def __getattr__(self, name: str):
                    return getattr(self._connection, name)

            def parse_persist_document(*, document_key: str):
                processed.append(document_key)
                return None

            def enrich_document(*, document_key: str):
                return None

            original_connect = document_processing_module.sqlite3.connect

            def connect_with_retry_once(*args, **kwargs):
                return RetryOnceListConnection(original_connect(*args, **kwargs))

            with mock.patch.object(
                document_processing_module,
                "DATABASE_RETRY_DELAYS_SECONDS",
                (0.0, 0.0, 0.0),
                create=True,
            ):
                with mock.patch.object(
                    document_processing_module.sqlite3,
                    "connect",
                    side_effect=connect_with_retry_once,
                ):
                    drain_result = run_document_processing_drain(
                        database_url=database_url,
                        process_one_document=lambda **kwargs: process_document(
                            database_url=database_url,
                            parse_persist_document=parse_persist_document,
                            enrich_document=enrich_document,
                            **kwargs,
                        ),
                        document_limit=1,
                        scheduler_run_id="scheduler-run-1",
                    )
            stored_run = get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(list_attempts, 3)
        self.assertEqual(processed, [document_key])
        self.assertTrue(drain_result.did_work)
        self.assertEqual(drain_result.selected_count, 1)
        self.assertEqual(drain_result.completed_count, 1)
        self.assertEqual(drain_result.failed_count, 0)
        self.assertEqual(stored_run.status, "succeeded")

    def test_create_scheduler_run_retries_transient_database_lock_on_readback(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_scheduler_run)
        self.assertIsNotNone(document_processing_module)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            read_attempts = 0

            class RetryOnceSchedulerReadConnection:
                def __init__(self, connection):
                    self._connection = connection

                def execute(self, sql, parameters=()):
                    nonlocal read_attempts
                    if "FROM scheduler_runs" in sql and "WHERE scheduler_run_id = ?" in sql:
                        read_attempts += 1
                        if read_attempts == 1:
                            raise sqlite3.OperationalError("database is locked")
                    return self._connection.execute(sql, parameters)

                def __getattr__(self, name: str):
                    return getattr(self._connection, name)

            original_connect = document_processing_module.sqlite3.connect

            def connect_with_retry_once(*args, **kwargs):
                return RetryOnceSchedulerReadConnection(original_connect(*args, **kwargs))

            with mock.patch.object(
                document_processing_module,
                "DATABASE_RETRY_DELAYS_SECONDS",
                (0.0, 0.0, 0.0),
            ):
                with mock.patch.object(
                    document_processing_module.sqlite3,
                    "connect",
                    side_effect=connect_with_retry_once,
                ):
                    scheduler_run = create_scheduler_run(
                        database_url=database_url,
                        trigger_type="processing",
                    )

        self.assertEqual(read_attempts, 2)
        self.assertEqual(scheduler_run.trigger_type, "processing")
        self.assertEqual(scheduler_run.status, "running")

    def test_claim_document_processing_run_retries_transient_database_lock_on_readback(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_document_processing_run)
        self.assertIsNotNone(claim_document_processing_run)
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

            read_attempts = 0

            class RetryOnceDocumentReadConnection:
                def __init__(self, connection):
                    self._connection = connection

                def execute(self, sql, parameters=()):
                    nonlocal read_attempts
                    if "FROM document_processing_runs" in sql and "WHERE document_key = ?" in sql:
                        read_attempts += 1
                        if read_attempts == 1:
                            raise sqlite3.OperationalError("database is locked")
                    return self._connection.execute(sql, parameters)

                def __getattr__(self, name: str):
                    return getattr(self._connection, name)

            original_connect = document_processing_module.sqlite3.connect

            def connect_with_retry_once(*args, **kwargs):
                return RetryOnceDocumentReadConnection(original_connect(*args, **kwargs))

            with mock.patch.object(
                document_processing_module,
                "DATABASE_RETRY_DELAYS_SECONDS",
                (0.0, 0.0, 0.0),
            ):
                with mock.patch.object(
                    document_processing_module.sqlite3,
                    "connect",
                    side_effect=connect_with_retry_once,
                ):
                    claimed_run = claim_document_processing_run(
                        database_url=database_url,
                        document_key=document_key,
                        locked_by="scheduler-worker-1",
                        lock_timeout_seconds=600,
                        scheduler_run_id="scheduler-run-1",
                    )

        self.assertEqual(read_attempts, 2)
        self.assertIsNotNone(claimed_run)
        self.assertEqual(claimed_run.status, "running")
        self.assertEqual(claimed_run.locked_by, "scheduler-worker-1")

    def test_claim_article_processing_run_retries_transient_database_lock_on_readback(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(claim_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(document_processing_module)

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

            read_attempts = 0

            class RetryOnceArticleReadConnection:
                def __init__(self, connection):
                    self._connection = connection

                def execute(self, sql, parameters=()):
                    nonlocal read_attempts
                    if "FROM article_processing_runs" in sql and "WHERE article_key = ?" in sql:
                        read_attempts += 1
                        if read_attempts == 1:
                            raise sqlite3.OperationalError("database is locked")
                    return self._connection.execute(sql, parameters)

                def __getattr__(self, name: str):
                    return getattr(self._connection, name)

            original_connect = document_processing_module.sqlite3.connect

            def connect_with_retry_once(*args, **kwargs):
                return RetryOnceArticleReadConnection(original_connect(*args, **kwargs))

            with mock.patch.object(
                document_processing_module,
                "DATABASE_RETRY_DELAYS_SECONDS",
                (0.0, 0.0, 0.0),
            ):
                with mock.patch.object(
                    document_processing_module.sqlite3,
                    "connect",
                    side_effect=connect_with_retry_once,
                ):
                    claimed_run = claim_article_processing_run(
                        database_url=database_url,
                        article_key=article.article_key,
                        locked_by="article-worker-1",
                        lock_timeout_seconds=600,
                    )

        self.assertEqual(read_attempts, 2)
        self.assertIsNotNone(claimed_run)
        self.assertEqual(claimed_run.status, "running")
        self.assertEqual(claimed_run.locked_by, "article-worker-1")

    def test_run_processing_tick_retries_persistent_database_lock_three_times_then_reraises(self) -> None:
        self.assertIsNotNone(run_processing_tick)
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

            list_attempts = 0

            class AlwaysLockedListConnection:
                def __init__(self, connection):
                    self._connection = connection

                def execute(self, sql, parameters=()):
                    nonlocal list_attempts
                    if "FROM document_processing_runs" in sql and "WHERE status IN ('manual_retry_requested', 'pending', 'failed_retryable')" in sql:
                        list_attempts += 1
                        raise sqlite3.OperationalError("database is locked")
                    return self._connection.execute(sql, parameters)

                def __getattr__(self, name: str):
                    return getattr(self._connection, name)

            original_connect = document_processing_module.sqlite3.connect

            def connect_with_persistent_lock(*args, **kwargs):
                return AlwaysLockedListConnection(original_connect(*args, **kwargs))

            with mock.patch.object(
                document_processing_module,
                "DATABASE_RETRY_DELAYS_SECONDS",
                (0.0, 0.0, 0.0),
                create=True,
            ):
                with mock.patch.object(
                    document_processing_module.sqlite3,
                    "connect",
                    side_effect=connect_with_persistent_lock,
                ):
                    with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
                        run_processing_tick(
                            database_url=database_url,
                            trigger_type="processing",
                            process_one_document=lambda **kwargs: None,
                            document_limit=1,
                        )

        self.assertEqual(list_attempts, 4)

    def test_article_processing_drain_refills_free_slots_until_queue_is_empty(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(run_article_processing_drain)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(process_article_processing_run)
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
                article_count=5,
            )
            articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            for article in articles:
                create_article_processing_run(
                    database_url=database_url,
                    article_id=article.article_id,
                )

            in_flight: list[str] = []
            processed: list[str] = []
            peak_in_flight = 0
            lock = threading.Lock()

            def process_one_article(*, article_key: str, locked_by: str):
                nonlocal peak_in_flight
                with lock:
                    in_flight.append(article_key)
                    peak_in_flight = max(peak_in_flight, len(in_flight))
                try:
                    time.sleep(0.05)
                    result = process_article_processing_run(
                        database_url=database_url,
                        article_key=article_key,
                        locked_by=locked_by,
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
                    processed.append(article_key)
                    return result
                finally:
                    with lock:
                        in_flight.remove(article_key)

            drain_result = run_article_processing_drain(
                database_url=database_url,
                process_one_article=process_one_article,
                article_limit=2,
            )
            stored_runs = [
                get_article_processing_run(
                    database_url=database_url,
                    article_key=article.article_key,
                )
                for article in articles
            ]

        self.assertCountEqual(processed, [article.article_key for article in articles])
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

    def test_article_processing_drain_preserves_manual_retry_override_with_stable_callback_shape(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(run_article_processing_drain)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(request_manual_article_retry)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(process_article_processing_run)
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
            drain_result = run_article_processing_drain(
                database_url=database_url,
                process_one_article=lambda *, article_key, locked_by: process_article_processing_run(
                    database_url=database_url,
                    article_key=article_key,
                    locked_by=locked_by,
                    translator=translator,
                    summarizer_tagger=summarizer,
                    provider_name="gemini",
                    model_name="gemini-2.5-flash",
                    prompt_version="article-enrichment-v2",
                    lock_timeout_seconds=600,
                ),
                article_limit=1,
            )
            stored_run = get_article_processing_run(
                database_url=database_url,
                article_key=article.article_key,
            )

        self.assertEqual(first_run.status, "succeeded")
        self.assertTrue(drain_result.did_work)
        self.assertEqual(drain_result.selected_count, 1)
        self.assertEqual(drain_result.completed_count, 1)
        self.assertEqual(drain_result.failed_count, 0)
        self.assertEqual(stored_run.status, "succeeded")
        self.assertEqual(len(translator_calls), 2)

    def test_article_processing_drain_skips_contended_claim_before_submit(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(run_article_processing_drain)
        self.assertIsNotNone(create_article_processing_run)
        self.assertIsNotNone(get_article_processing_run)
        self.assertIsNotNone(process_article_processing_run)
        self.assertIsNotNone(claim_article_processing_run)
        self.assertIsNotNone(list_latest_document_articles)
        self.assertIsNotNone(ArticleTranslationResult)
        self.assertIsNotNone(ArticleSummaryTagResult)
        self.assertIsNotNone(document_processing_module)

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
                article_count=2,
            )
            articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )
            for article in articles:
                create_article_processing_run(
                    database_url=database_url,
                    article_id=article.article_id,
                )
            first_article_key = articles[0].article_key
            second_article_key = articles[1].article_key
            processed: list[str] = []
            original_claim_article_processing_run = claim_article_processing_run

            def contend_second_claim(**kwargs):
                if kwargs["article_key"] == second_article_key:
                    original_claim_article_processing_run(
                        database_url=database_url,
                        article_key=second_article_key,
                        locked_by="other-worker",
                        lock_timeout_seconds=600,
                    )
                return original_claim_article_processing_run(**kwargs)

            def process_one_article(*, article_key: str, locked_by: str):
                processed.append(article_key)
                return process_article_processing_run(
                    database_url=database_url,
                    article_key=article_key,
                    locked_by=locked_by,
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

            with mock.patch.object(
                document_processing_module,
                "claim_article_processing_run",
                side_effect=contend_second_claim,
            ):
                drain_result = run_article_processing_drain(
                    database_url=database_url,
                    process_one_article=process_one_article,
                    article_limit=2,
                )
            first_stored_run = get_article_processing_run(
                database_url=database_url,
                article_key=first_article_key,
            )
            second_stored_run = get_article_processing_run(
                database_url=database_url,
                article_key=second_article_key,
            )

        self.assertEqual(processed, [first_article_key])
        self.assertTrue(drain_result.did_work)
        self.assertEqual(drain_result.selected_count, 1)
        self.assertEqual(drain_result.completed_count, 1)
        self.assertEqual(drain_result.failed_count, 0)
        self.assertEqual(drain_result.error_messages, ())
        self.assertEqual(first_stored_run.status, "succeeded")
        self.assertEqual(second_stored_run.status, "running")
        self.assertEqual(second_stored_run.locked_by, "other-worker")


if __name__ == "__main__":
    unittest.main()
