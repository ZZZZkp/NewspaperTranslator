import json
import sqlite3
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.worker import (
        build_run_article_processing_tick_from_env,
        build_run_import_tick_from_env,
        build_run_processing_tick_from_env,
        build_startup_report,
        build_startup_log_line,
        build_run_scheduler_tick_from_env,
        get_last_import_run_started_at,
        run_startup_maintenance,
        run_worker_loop,
        should_run_catch_up_tick,
    )
except ImportError:
    build_run_article_processing_tick_from_env = None
    build_startup_log_line = None
    build_startup_report = None
    build_run_import_tick_from_env = None
    build_run_processing_tick_from_env = None
    build_run_scheduler_tick_from_env = None
    get_last_import_run_started_at = None
    run_pending_migrations = None
    run_startup_maintenance = None
    run_worker_loop = None
    should_run_catch_up_tick = None


class WorkerStartupTests(unittest.TestCase):
    def test_builds_a_worker_startup_report_with_database_status(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            build_startup_report,
            "build_startup_report should be importable from newspaper_translator.worker",
        )
        self.assertIsNotNone(
            build_startup_log_line,
            "build_startup_log_line should be importable from newspaper_translator.worker",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            env = {
                "APP_ENV": "test",
                "DATABASE_URL": database_url,
                "STORAGE_ROOT": temp_dir,
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            }

            report = build_startup_report(env)
            log_line = build_startup_log_line(env, timestamp="2026-04-22T13:10:00Z")

        payload = json.loads(log_line)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["service"], "worker")
        self.assertEqual(report["app_env"], "test")
        self.assertEqual(report["database"]["status"], "ok")
        self.assertEqual(payload["event"], "worker.startup")
        self.assertEqual(payload["service"], "worker")
        self.assertEqual(payload["details"]["status"], "ok")

    def test_runs_catch_up_tick_when_no_previous_scheduler_run_exists(self) -> None:
        self.assertIsNotNone(should_run_catch_up_tick)

        should_run = should_run_catch_up_tick(
            last_scheduler_run_started_at=None,
            now="2026-04-28T12:00:00",
            interval_seconds=7200,
        )

        self.assertEqual(should_run, True)

    def test_runs_catch_up_tick_when_previous_scheduler_run_is_overdue(self) -> None:
        self.assertIsNotNone(should_run_catch_up_tick)

        should_run = should_run_catch_up_tick(
            last_scheduler_run_started_at="2026-04-28T08:59:59",
            now="2026-04-28T12:00:00",
            interval_seconds=7200,
        )

        self.assertEqual(should_run, True)

    def test_skips_catch_up_tick_when_previous_scheduler_run_is_still_fresh(self) -> None:
        self.assertIsNotNone(should_run_catch_up_tick)

        should_run = should_run_catch_up_tick(
            last_scheduler_run_started_at="2026-04-28T10:30:00",
            now="2026-04-28T12:00:00",
            interval_seconds=7200,
        )

        self.assertEqual(should_run, False)

    def test_startup_maintenance_runs_recovery_and_catch_up_when_overdue(self) -> None:
        self.assertIsNotNone(run_startup_maintenance)

        calls: list[tuple[str, str | None]] = []

        def recover_documents() -> list[str]:
            calls.append(("recover_documents", None))
            return ["message-1:attachment-1:hash-1"]

        def recover_articles() -> list[str]:
            calls.append(("recover_articles", None))
            return ["article-key-1"]

        def run_tick(*, trigger_type: str) -> str:
            calls.append(("tick", trigger_type))
            return "scheduler-run-1"

        result = run_startup_maintenance(
            last_scheduler_run_started_at="2026-04-28T08:00:00",
            now="2026-04-28T12:00:00",
            interval_seconds=7200,
            recover_stale_document_runs=recover_documents,
            recover_stale_article_runs=recover_articles,
            run_scheduler_tick=run_tick,
        )

        self.assertEqual(
            calls,
            [("recover_documents", None), ("recover_articles", None), ("tick", "interval")],
        )
        self.assertEqual(result["recovered_document_keys"], ["message-1:attachment-1:hash-1"])
        self.assertEqual(result["recovered_article_keys"], ["article-key-1"])
        self.assertEqual(result["catch_up_triggered"], True)
        self.assertEqual(result["scheduler_run_id"], "scheduler-run-1")

    def test_startup_maintenance_skips_catch_up_when_scheduler_is_fresh(self) -> None:
        self.assertIsNotNone(run_startup_maintenance)

        calls: list[tuple[str, str | None]] = []

        def recover_documents() -> list[str]:
            calls.append(("recover_documents", None))
            return []

        def recover_articles() -> list[str]:
            calls.append(("recover_articles", None))
            return []

        def run_tick(*, trigger_type: str) -> str:
            calls.append(("tick", trigger_type))
            return "scheduler-run-1"

        result = run_startup_maintenance(
            last_scheduler_run_started_at="2026-04-28T10:30:00",
            now="2026-04-28T12:00:00",
            interval_seconds=7200,
            recover_stale_document_runs=recover_documents,
            recover_stale_article_runs=recover_articles,
            run_scheduler_tick=run_tick,
        )

        self.assertEqual(calls, [("recover_documents", None), ("recover_articles", None)])
        self.assertEqual(result["recovered_document_keys"], [])
        self.assertEqual(result["recovered_article_keys"], [])
        self.assertEqual(result["catch_up_triggered"], False)
        self.assertEqual(result["scheduler_run_id"], None)

    def test_build_run_scheduler_tick_from_env_wires_real_import_and_document_dependencies(self) -> None:
        self.assertIsNotNone(build_run_scheduler_tick_from_env)

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
                "STORAGE_ROOT": temp_dir,
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "MINERU_API_TOKEN": "mineru-token",
                "MINERU_MODEL_VERSION": "vlm",
                "DEEPSEEK_API_KEY": "deepseek-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-chat",
            }

            with patch("newspaper_translator.worker.import_from_gmail") as import_from_gmail:
                with patch("newspaper_translator.worker.process_document") as process_document:
                    with patch("newspaper_translator.worker.MineruClient") as mineru_client_class:
                        with patch("newspaper_translator.worker.DeepSeekContinuationMatcher") as matcher_class:
                            with patch("newspaper_translator.worker.DeepSeekArticleTranslator") as translator_class:
                                with patch("newspaper_translator.worker.DeepSeekArticleSummarizerTagger") as summarizer_class:
                                    with patch("newspaper_translator.worker.run_scheduler_tick") as run_scheduler_tick:
                                        import_from_gmail.return_value = SimpleNamespace(run_id="import-run-1")
                                        process_document.return_value = SimpleNamespace(status="succeeded")
                                        mineru_client_class.return_value = SimpleNamespace(name="mineru-client")
                                        matcher_class.return_value = SimpleNamespace(name="continuation-matcher")
                                        translator_class.return_value = SimpleNamespace(name="translator")
                                        summarizer_class.return_value = SimpleNamespace(name="summarizer")

                                        def fake_run_scheduler_tick(**kwargs):
                                            import_result = kwargs["import_documents"]()
                                            self.assertEqual(import_result.run_id, "import-run-1")
                                            process_result = kwargs["process_one_document"](
                                                document_key="message-1:attachment-1:hash-1",
                                                scheduler_run_id="scheduler-run-1",
                                                locked_by="scheduler-worker-1",
                                            )
                                            self.assertEqual(process_result.status, "succeeded")
                                            return SimpleNamespace(scheduler_run_id="scheduler-run-1")

                                        run_scheduler_tick.side_effect = fake_run_scheduler_tick

                                        run_tick = build_run_scheduler_tick_from_env(env)
                                        scheduler_run_id = run_tick(trigger_type="interval")

        self.assertEqual(scheduler_run_id, "scheduler-run-1")
        self.assertEqual(import_from_gmail.call_args.kwargs["config_path"], pathlib.Path("/tmp/gmail-config.json"))
        self.assertEqual(import_from_gmail.call_args.kwargs["storage_root"], pathlib.Path(temp_dir))
        self.assertEqual(import_from_gmail.call_args.kwargs["database_url"], "sqlite:////tmp/newspaper-translator.db")
        self.assertEqual(run_scheduler_tick.call_args.kwargs["database_url"], "sqlite:////tmp/newspaper-translator.db")
        self.assertEqual(run_scheduler_tick.call_args.kwargs["trigger_type"], "interval")
        self.assertEqual(run_scheduler_tick.call_args.kwargs["document_limit"], 2)
        self.assertNotIn("article_limit", run_scheduler_tick.call_args.kwargs)
        self.assertEqual(process_document.call_args.kwargs["database_url"], "sqlite:////tmp/newspaper-translator.db")
        self.assertEqual(
            process_document.call_args.kwargs["output_root"],
            pathlib.Path(temp_dir) / "phase3-output",
        )
        self.assertEqual(process_document.call_args.kwargs["provider_name"], "deepseek")
        self.assertEqual(process_document.call_args.kwargs["model_name"], "deepseek-chat")
        self.assertEqual(process_document.call_args.kwargs["prompt_version"], "article-enrichment-v2")
        self.assertEqual(process_document.call_args.kwargs["translator"].name, "translator")
        self.assertEqual(process_document.call_args.kwargs["summarizer_tagger"].name, "summarizer")
        self.assertEqual(process_document.call_args.kwargs["continuation_matcher"].name, "continuation-matcher")

    def test_build_run_article_processing_tick_from_env_wires_deepseek_dependencies(self) -> None:
        from newspaper_translator.worker import build_run_article_processing_tick_from_env

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "DEEPSEEK_API_KEY": "deepseek-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-chat",
        }

        with patch("newspaper_translator.worker.process_article_processing_run") as process_article:
            with patch("newspaper_translator.worker.DeepSeekArticleTranslator") as translator_class:
                with patch("newspaper_translator.worker.DeepSeekArticleSummarizerTagger") as summarizer_class:
                    with patch("newspaper_translator.worker.run_article_processing_drain") as drain:
                        translator_class.return_value = SimpleNamespace(name="translator")
                        summarizer_class.return_value = SimpleNamespace(name="summarizer")
                        process_article.return_value = SimpleNamespace(status="succeeded")

                        def fake_drain(**kwargs):
                            result = kwargs["process_one_article"](
                                article_key="article-key-1",
                                locked_by="worker-1",
                            )
                            self.assertEqual(result.status, "succeeded")
                            return SimpleNamespace(did_work=True)

                        drain.side_effect = fake_drain

                        run_tick = build_run_article_processing_tick_from_env(env)
                        run_tick()

        self.assertEqual(process_article.call_args.kwargs["provider_name"], "deepseek")
        self.assertEqual(process_article.call_args.kwargs["model_name"], "deepseek-chat")
        self.assertEqual(process_article.call_args.kwargs["translator"].name, "translator")
        self.assertEqual(process_article.call_args.kwargs["summarizer_tagger"].name, "summarizer")

    def test_last_import_started_at_uses_import_runs_not_processing_scheduler_runs(self) -> None:
        self.assertIsNotNone(get_last_import_run_started_at)

        with patch("newspaper_translator.worker.list_import_runs") as list_import_runs:
            list_import_runs.return_value = [
                SimpleNamespace(started_at="2026-05-06T09:15:00")
            ]

            started_at = get_last_import_run_started_at(
                database_url="sqlite:////tmp/newspaper-translator.db",
            )

        self.assertEqual(started_at, "2026-05-06T09:15:00")
        self.assertEqual(list_import_runs.call_args.kwargs["database_url"], "sqlite:////tmp/newspaper-translator.db")
        self.assertEqual(list_import_runs.call_args.kwargs["limit"], 1)

    def test_worker_loop_runs_processing_each_poll_without_overdue_import(self) -> None:
        self.assertIsNotNone(run_worker_loop)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "GMAIL_IMPORT_INTERVAL_SECONDS": "7200",
            "PROCESSING_POLL_INTERVAL_SECONDS": "60",
        }
        now_values = iter(
            [
                "2026-05-06T12:00:00",
                "2026-05-06T12:00:00",
            ]
        )
        import_started_values = iter(
            [
                "2026-05-06T11:30:00",
                "2026-05-06T11:30:00",
            ]
        )
        calls: list[tuple[str, str | None]] = []
        sleep_calls: list[int] = []

        def fake_startup_maintenance(**kwargs):
            calls.append(("startup", kwargs["last_scheduler_run_started_at"]))
            return {
                "recovered_document_keys": [],
                "recovered_article_keys": [],
                "catch_up_triggered": False,
                "scheduler_run_id": None,
            }

        def fake_get_last_started_at(*, database_url: str) -> str | None:
            self.assertEqual(database_url, "sqlite:////tmp/newspaper-translator.db")
            return next(import_started_values)

        def fake_processing_tick() -> str:
            calls.append(("processing", None))
            return "processing-run-1"

        def fake_import_tick(*, trigger_type: str) -> str:
            calls.append(("import", trigger_type))
            return "import-run-1"

        run_worker_loop(
            env=env,
            now_fn=lambda: next(now_values),
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=1,
            run_startup_maintenance_fn=fake_startup_maintenance,
            get_last_scheduler_run_started_at_fn=fake_get_last_started_at,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=fake_import_tick,
            run_processing_tick_fn=fake_processing_tick,
        )

        self.assertEqual(calls, [("startup", "2026-05-06T11:30:00"), ("processing", None)])
        self.assertEqual(sleep_calls, [60])

    def test_worker_loop_runs_import_when_import_interval_is_overdue(self) -> None:
        self.assertIsNotNone(run_worker_loop)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "GMAIL_IMPORT_INTERVAL_SECONDS": "7200",
            "PROCESSING_POLL_INTERVAL_SECONDS": "60",
        }
        calls: list[tuple[str, str | None]] = []

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-06T12:31:00",
            sleep_fn=lambda seconds: None,
            max_loops=1,
            run_startup_maintenance_fn=lambda **kwargs: calls.append(
                ("startup", kwargs["last_scheduler_run_started_at"])
            ),
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-06T10:30:00",
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: calls.append(
                ("import", trigger_type)
            ) or "import-run-1",
            run_processing_tick_fn=lambda: calls.append(("processing", None)) or "processing-run-1",
        )

        self.assertEqual(
            calls,
            [
                ("startup", "2026-05-06T10:30:00"),
                ("import", "interval"),
                ("processing", None),
            ],
        )

    def test_worker_loop_runs_periodic_import_and_processing_when_import_becomes_overdue(self) -> None:
        self.assertIsNotNone(run_worker_loop)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
        }
        now_values = iter(
            [
                "2026-04-28T11:00:00",
                "2026-04-28T12:31:00",
            ]
        )
        last_started_values = iter(
            [
                "2026-04-28T10:30:00",
                "2026-04-28T10:30:00",
            ]
        )
        calls: list[tuple[str, str | None]] = []
        sleep_calls: list[int] = []

        def fake_now() -> str:
            return next(now_values)

        def fake_startup_maintenance(**kwargs):
            calls.append(("startup", kwargs["last_scheduler_run_started_at"]))
            return {
                "recovered_document_keys": [],
                "catch_up_triggered": False,
                "scheduler_run_id": None,
            }

        def fake_get_last_started_at(*, database_url: str) -> str | None:
            self.assertEqual(database_url, "sqlite:////tmp/newspaper-translator.db")
            return next(last_started_values)

        def fake_run_tick(*, trigger_type: str) -> str:
            calls.append(("import", trigger_type))
            return "import-run-1"

        run_worker_loop(
            env=env,
            now_fn=fake_now,
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=1,
            run_startup_maintenance_fn=fake_startup_maintenance,
            get_last_scheduler_run_started_at_fn=fake_get_last_started_at,
            run_import_tick_fn=fake_run_tick,
            run_processing_tick_fn=lambda: calls.append(("processing", None)) or "processing-run-1",
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
        )

        self.assertEqual(
            calls,
            [
                ("startup", "2026-04-28T10:30:00"),
                ("import", "interval"),
                ("processing", None),
            ],
        )
        self.assertEqual(sleep_calls, [60])


class WorkerThroughputDefaultsTests(unittest.TestCase):
    def test_default_article_worker_concurrency_is_four(self) -> None:
        from newspaper_translator.worker import _read_int_setting

        env: dict[str, str] = {}
        article_concurrency = _read_int_setting(
            env,
            "ARTICLE_WORKER_CONCURRENCY",
            default=4,
        )
        document_concurrency = _read_int_setting(
            env,
            "DOCUMENT_WORKER_CONCURRENCY",
            default=2,
        )

        self.assertEqual(article_concurrency, 4)
        self.assertEqual(document_concurrency, 2)

    def test_default_article_worker_batch_size_is_eight(self) -> None:
        from newspaper_translator.worker import _read_int_setting

        env: dict[str, str] = {}
        batch_size = _read_int_setting(
            env,
            "ARTICLE_WORKER_BATCH_SIZE",
            default=8,
        )
        self.assertEqual(batch_size, 8)

    def test_active_interval_is_used_when_processing_did_work(self) -> None:
        from newspaper_translator.worker import run_worker_loop
        from types import SimpleNamespace

        sleep_calls: list[int] = []

        def fake_sleep(seconds: int) -> None:
            sleep_calls.append(seconds)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///:memory:",
            "STORAGE_ROOT": "/tmp",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS": "10",
            "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        def stub_processing_tick():
            return SimpleNamespace(did_work=True, scheduler_run_id="run-1")

        def stub_run_startup_maintenance(**_kwargs):
            return {}

        def stub_get_last_started_at(*, database_url: str) -> str | None:
            return "2026-05-06T12:00:00"

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-06T12:00:00",
            sleep_fn=fake_sleep,
            max_loops=1,
            run_startup_maintenance_fn=stub_run_startup_maintenance,
            get_last_scheduler_run_started_at_fn=stub_get_last_started_at,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(sleep_calls, [10])

    def test_idle_interval_is_used_when_processing_finds_no_work(self) -> None:
        from newspaper_translator.worker import run_worker_loop
        from types import SimpleNamespace

        sleep_calls: list[int] = []

        def fake_sleep(seconds: int) -> None:
            sleep_calls.append(seconds)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///:memory:",
            "STORAGE_ROOT": "/tmp",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS": "10",
            "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        def stub_processing_tick():
            return SimpleNamespace(did_work=False, scheduler_run_id=None)

        def stub_run_startup_maintenance(**_kwargs):
            return {}

        def stub_get_last_started_at(*, database_url: str) -> str | None:
            return "2026-05-06T12:00:00"

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-06T12:00:00",
            sleep_fn=fake_sleep,
            max_loops=1,
            run_startup_maintenance_fn=stub_run_startup_maintenance,
            get_last_scheduler_run_started_at_fn=stub_get_last_started_at,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(sleep_calls, [60])


class WorkerErrorHelperTests(unittest.TestCase):
    def test_loop_retry_backoff_seconds_caps_at_sixty_seconds(self) -> None:
        from newspaper_translator.worker import _loop_retry_backoff_seconds

        self.assertEqual(_loop_retry_backoff_seconds(1), 5)
        self.assertEqual(_loop_retry_backoff_seconds(2), 15)
        self.assertEqual(_loop_retry_backoff_seconds(3), 60)
        self.assertEqual(_loop_retry_backoff_seconds(8), 60)

    def test_database_locked_operational_error_is_retryable(self) -> None:
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertEqual(
            _is_retryable_worker_loop_error(
                sqlite3.OperationalError("database is locked")
            ),
            True,
        )

    def test_read_timeout_is_retryable(self) -> None:
        import requests
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertTrue(
            _is_retryable_worker_loop_error(
                requests.exceptions.ReadTimeout("read timed out")
            )
        )

    def test_connect_timeout_is_retryable(self) -> None:
        import requests
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertTrue(
            _is_retryable_worker_loop_error(
                requests.exceptions.ConnectTimeout("connect timed out")
            )
        )

    def test_connection_error_is_retryable(self) -> None:
        import requests
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertTrue(
            _is_retryable_worker_loop_error(
                requests.exceptions.ConnectionError("connection refused")
            )
        )

    def test_non_locked_operational_error_is_not_retryable(self) -> None:
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertEqual(
            _is_retryable_worker_loop_error(
                sqlite3.OperationalError("no such table: import_runs")
            ),
            False,
        )

    def test_value_error_is_treated_as_fatal(self) -> None:
        from newspaper_translator.worker import _is_fatal_worker_error

        self.assertEqual(_is_fatal_worker_error(ValueError("bad env")), True)

    def test_raise_for_worker_loop_error_wraps_fatal_errors_with_stage(self) -> None:
        from newspaper_translator.worker import (
            FatalWorkerError,
            _raise_for_worker_loop_error,
        )

        with self.assertRaises(FatalWorkerError) as context:
            try:
                raise ValueError("bad env")
            except ValueError as exc:
                _raise_for_worker_loop_error(exc, stage="import_tick")

        self.assertEqual(context.exception.stage, "import_tick")
        self.assertIsInstance(context.exception.cause, ValueError)
        self.assertEqual(str(context.exception.cause), "bad env")
        self.assertIs(context.exception.__cause__, context.exception.cause)

    def test_raise_for_worker_loop_error_wraps_retryable_errors_with_stage(self) -> None:
        from newspaper_translator.worker import (
            RetryableWorkerLoopError,
            _raise_for_worker_loop_error,
        )

        with self.assertRaises(RetryableWorkerLoopError) as context:
            try:
                raise sqlite3.OperationalError("database is locked")
            except sqlite3.OperationalError as exc:
                _raise_for_worker_loop_error(exc, stage="import_tick")

        self.assertEqual(context.exception.stage, "import_tick")
        self.assertIsInstance(context.exception.cause, sqlite3.OperationalError)
        self.assertEqual(str(context.exception.cause), "database is locked")
        self.assertIs(context.exception.__cause__, context.exception.cause)

    def test_raise_for_worker_loop_error_preserves_existing_fatal_wrapper(self) -> None:
        from newspaper_translator.worker import FatalWorkerError, _raise_for_worker_loop_error

        wrapped_error = FatalWorkerError(
            "fatal worker error during config",
            stage="config",
            cause=ValueError("bad env"),
        )

        with self.assertRaises(FatalWorkerError) as context:
            _raise_for_worker_loop_error(wrapped_error, stage="import_tick")

        self.assertIs(context.exception, wrapped_error)
        self.assertEqual(context.exception.stage, "config")
        self.assertIsInstance(context.exception.cause, ValueError)
        self.assertIs(context.exception.__cause__, context.exception.cause)


class WorkerRoleDispatchTests(unittest.TestCase):
    def test_worker_loop_dispatches_import_role_to_import_and_document_processing(self) -> None:
        calls: list[tuple[str, str | None]] = []
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "import",
            "GMAIL_IMPORT_INTERVAL_SECONDS": "7200",
        }

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-07T12:00:00",
            sleep_fn=lambda seconds: None,
            max_loops=1,
            run_import_tick_fn=lambda *, trigger_type: calls.append(("import", trigger_type)) or "import-run-1",
            run_processing_tick_fn=lambda: calls.append(("document-drain", None)) or SimpleNamespace(did_work=True),
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-07T09:00:00",
            run_startup_maintenance_fn=lambda **kwargs: calls.append(("startup", kwargs["last_scheduler_run_started_at"])) or {},
        )

        self.assertEqual(
            calls,
            [("startup", "2026-05-07T09:00:00"), ("import", "interval"), ("document-drain", None)],
        )

    def test_worker_loop_dispatches_article_role_to_idle_probe_and_article_drain(self) -> None:
        calls: list[str] = []
        sleep_calls: list[int] = []
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "article",
            "ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-07T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=2,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: calls.append("recover") or [],
            run_article_processing_tick_fn=lambda: calls.append("article-drain") or SimpleNamespace(did_work=False),
            article_work_exists_fn=lambda: False,
        )

        self.assertEqual(calls, ["recover"])
        self.assertEqual(sleep_calls, [60, 60])

    def test_worker_loop_article_role_drains_when_work_exists(self) -> None:
        calls: list[str] = []
        sleep_calls: list[int] = []
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "article",
            "ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS": "30",
        }

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-07T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=1,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_article_processing_tick_fn=lambda: calls.append("article-drain") or SimpleNamespace(did_work=True),
            article_work_exists_fn=lambda: True,
        )

        self.assertIn("article-drain", calls)
        self.assertEqual(sleep_calls, [30])


class ImportWorkerLoopFailureHandlingTests(unittest.TestCase):
    def test_import_worker_backs_off_after_retryable_processing_failure(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []
        attempts = {"count": 0}

        def stub_processing_tick():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return SimpleNamespace(did_work=False)

        run_worker_loop(
            env={
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "STORAGE_ROOT": "/tmp",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
            },
            now_fn=lambda: "2026-05-07T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=2,
            run_startup_maintenance_fn=lambda **_kwargs: {},
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-07T12:00:00",
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleep_calls, [5, 60])

    def test_import_worker_backs_off_after_retryable_table_locked_processing_failure(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []
        attempts = {"count": 0}

        def stub_processing_tick():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise sqlite3.OperationalError("database table is locked")
            return SimpleNamespace(did_work=False)

        run_worker_loop(
            env={
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "STORAGE_ROOT": "/tmp",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
            },
            now_fn=lambda: "2026-05-07T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=2,
            run_startup_maintenance_fn=lambda **_kwargs: {},
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-07T12:00:00",
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleep_calls, [5, 60])

    def test_import_worker_resets_failure_streak_after_later_success(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []
        attempts = {"count": 0}

        def stub_processing_tick():
            attempts["count"] += 1
            if attempts["count"] in (1, 3):
                raise sqlite3.OperationalError("database is locked")
            return SimpleNamespace(did_work=False)

        run_worker_loop(
            env={
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "STORAGE_ROOT": "/tmp",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
            },
            now_fn=lambda: "2026-05-07T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=4,
            run_startup_maintenance_fn=lambda **_kwargs: {},
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-07T12:00:00",
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(attempts["count"], 4)
        self.assertEqual(sleep_calls, [5, 60, 5, 60])

    def test_import_worker_raises_on_fatal_processing_failure(self) -> None:
        from newspaper_translator.worker import FatalWorkerError, run_worker_loop

        with self.assertRaises(FatalWorkerError) as context:
            run_worker_loop(
                env={
                    "APP_ENV": "test",
                    "DATABASE_URL": "sqlite:///:memory:",
                    "STORAGE_ROOT": "/tmp",
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                },
                now_fn=lambda: "2026-05-07T12:00:00",
                sleep_fn=lambda seconds: None,
                max_loops=1,
                run_startup_maintenance_fn=lambda **_kwargs: {},
                get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-07T12:00:00",
                recover_stale_document_runs_fn=lambda: [],
                recover_stale_article_runs_fn=lambda: [],
                run_import_tick_fn=lambda *, trigger_type: "import-1",
                run_processing_tick_fn=lambda: (_ for _ in ()).throw(ValueError("bad env")),
            )

        self.assertEqual(context.exception.stage, "processing_tick")
        self.assertIsInstance(context.exception.cause, ValueError)
        self.assertEqual(str(context.exception.cause), "bad env")


class ArticleWorkerLoopFailureHandlingTests(unittest.TestCase):
    def test_article_worker_backs_off_after_retryable_probe_failure(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []
        attempts = {"count": 0}

        def stub_article_work_exists() -> bool:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return False

        run_worker_loop(
            env={
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "STORAGE_ROOT": "/tmp",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "WORKER_ROLE": "article",
                "ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS": "60",
            },
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=2,
            recover_stale_article_runs_fn=lambda: [],
            run_article_processing_tick_fn=lambda: SimpleNamespace(did_work=False),
            article_work_exists_fn=stub_article_work_exists,
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleep_calls, [5, 60])

    def test_article_worker_raises_on_fatal_probe_failure(self) -> None:
        from newspaper_translator.worker import FatalWorkerError, run_worker_loop

        with self.assertRaises(FatalWorkerError) as context:
            run_worker_loop(
                env={
                    "APP_ENV": "test",
                    "DATABASE_URL": "sqlite:///:memory:",
                    "STORAGE_ROOT": "/tmp",
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                    "WORKER_ROLE": "article",
                },
                sleep_fn=lambda seconds: None,
                max_loops=1,
                recover_stale_article_runs_fn=lambda: [],
                run_article_processing_tick_fn=lambda: SimpleNamespace(did_work=False),
                article_work_exists_fn=lambda: (_ for _ in ()).throw(ValueError("bad env")),
            )

        self.assertEqual(context.exception.stage, "article_probe")
        self.assertIsInstance(context.exception.cause, ValueError)
        self.assertEqual(str(context.exception.cause), "bad env")

    def test_article_worker_backs_off_after_retryable_drain_failure(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []
        attempts = {"count": 0}

        def stub_article_processing_tick():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise sqlite3.OperationalError("database table is locked")
            return SimpleNamespace(did_work=False)

        run_worker_loop(
            env={
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "STORAGE_ROOT": "/tmp",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "WORKER_ROLE": "article",
                "ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS": "60",
            },
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=2,
            recover_stale_article_runs_fn=lambda: [],
            run_article_processing_tick_fn=stub_article_processing_tick,
            article_work_exists_fn=lambda: True,
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleep_calls, [5, 60])

    def test_article_worker_raises_on_fatal_drain_failure(self) -> None:
        from newspaper_translator.worker import FatalWorkerError, run_worker_loop

        with self.assertRaises(FatalWorkerError) as context:
            run_worker_loop(
                env={
                    "APP_ENV": "test",
                    "DATABASE_URL": "sqlite:///:memory:",
                    "STORAGE_ROOT": "/tmp",
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                    "WORKER_ROLE": "article",
                },
                sleep_fn=lambda seconds: None,
                max_loops=1,
                recover_stale_article_runs_fn=lambda: [],
                run_article_processing_tick_fn=lambda: (_ for _ in ()).throw(ValueError("bad env")),
                article_work_exists_fn=lambda: True,
            )

        self.assertEqual(context.exception.stage, "article_processing_tick")
        self.assertIsInstance(context.exception.cause, ValueError)
        self.assertEqual(str(context.exception.cause), "bad env")

    def test_article_worker_resets_failure_streak_after_later_successful_drain(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []
        attempts = {"count": 0}

        def stub_article_processing_tick():
            attempts["count"] += 1
            if attempts["count"] in (1, 3):
                raise sqlite3.OperationalError("database is locked")
            return SimpleNamespace(did_work=False)

        run_worker_loop(
            env={
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "STORAGE_ROOT": "/tmp",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "WORKER_ROLE": "article",
                "ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS": "60",
            },
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=4,
            recover_stale_article_runs_fn=lambda: [],
            run_article_processing_tick_fn=stub_article_processing_tick,
            article_work_exists_fn=lambda: True,
        )

        self.assertEqual(attempts["count"], 4)
        self.assertEqual(sleep_calls, [5, 60, 5, 60])


if __name__ == "__main__":
    unittest.main()
