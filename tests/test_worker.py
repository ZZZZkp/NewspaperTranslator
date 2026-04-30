import json
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
        build_startup_report,
        build_startup_log_line,
        build_run_scheduler_tick_from_env,
        run_startup_maintenance,
        run_worker_loop,
        should_run_catch_up_tick,
    )
except ImportError:
    build_startup_log_line = None
    build_startup_report = None
    build_run_scheduler_tick_from_env = None
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

    def test_build_run_scheduler_tick_from_env_wires_real_import_document_and_article_dependencies(self) -> None:
        self.assertIsNotNone(build_run_scheduler_tick_from_env)

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
                "STORAGE_ROOT": temp_dir,
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "MINERU_API_TOKEN": "mineru-token",
                "MINERU_MODEL_VERSION": "vlm",
                "GEMINI_TOKEN": "gemini-token",
                "GEMINI_MODEL": "gemini-2.5-flash",
            }

            with patch("newspaper_translator.worker.import_from_gmail") as import_from_gmail:
                with patch("newspaper_translator.worker.process_document") as process_document:
                    with patch("newspaper_translator.worker.process_article_processing_run") as process_article:
                        with patch("newspaper_translator.worker.MineruClient") as mineru_client_class:
                            with patch("newspaper_translator.worker.GeminiContinuationMatcher") as matcher_class:
                                with patch("newspaper_translator.worker.GeminiArticleTranslator") as translator_class:
                                    with patch("newspaper_translator.worker.GeminiArticleSummarizerTagger") as summarizer_class:
                                        with patch("newspaper_translator.worker.run_scheduler_tick") as run_scheduler_tick:
                                            import_from_gmail.return_value = SimpleNamespace(run_id="import-run-1")
                                            process_document.return_value = SimpleNamespace(status="succeeded")
                                            process_article.return_value = SimpleNamespace(status="succeeded")
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
                                                article_result = kwargs["process_one_article"](
                                                    article_key="article-key-1",
                                                    locked_by="article-worker-1",
                                                )
                                                self.assertEqual(article_result.status, "succeeded")
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
        self.assertEqual(run_scheduler_tick.call_args.kwargs["article_limit"], 2)
        self.assertEqual(process_document.call_args.kwargs["database_url"], "sqlite:////tmp/newspaper-translator.db")
        self.assertEqual(
            process_document.call_args.kwargs["output_root"],
            pathlib.Path(temp_dir) / "phase3-output",
        )
        self.assertEqual(process_document.call_args.kwargs["provider_name"], "gemini")
        self.assertEqual(process_document.call_args.kwargs["model_name"], "gemini-2.5-flash")
        self.assertEqual(process_document.call_args.kwargs["prompt_version"], "article-enrichment-v2")
        self.assertEqual(process_document.call_args.kwargs["translator"].name, "translator")
        self.assertEqual(process_document.call_args.kwargs["summarizer_tagger"].name, "summarizer")
        self.assertEqual(process_document.call_args.kwargs["continuation_matcher"].name, "continuation-matcher")
        self.assertEqual(process_article.call_args.kwargs["database_url"], "sqlite:////tmp/newspaper-translator.db")
        self.assertEqual(process_article.call_args.kwargs["provider_name"], "gemini")
        self.assertEqual(process_article.call_args.kwargs["model_name"], "gemini-2.5-flash")
        self.assertEqual(process_article.call_args.kwargs["prompt_version"], "article-enrichment-v2")
        self.assertEqual(process_article.call_args.kwargs["translator"].name, "translator")
        self.assertEqual(process_article.call_args.kwargs["summarizer_tagger"].name, "summarizer")

    def test_worker_loop_runs_periodic_tick_when_scheduler_becomes_overdue(self) -> None:
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
            calls.append(("tick", trigger_type))
            return "scheduler-run-1"

        run_worker_loop(
            env=env,
            now_fn=fake_now,
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=1,
            run_startup_maintenance_fn=fake_startup_maintenance,
            get_last_scheduler_run_started_at_fn=fake_get_last_started_at,
            run_scheduler_tick_fn=fake_run_tick,
            recover_stale_document_runs_fn=lambda: [],
        )

        self.assertEqual(calls, [("startup", "2026-04-28T10:30:00"), ("tick", "interval")])
        self.assertEqual(sleep_calls, [60])


if __name__ == "__main__":
    unittest.main()
