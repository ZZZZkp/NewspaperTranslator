import json
import pathlib
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.import_audit import (
        create_import_run,
        finalize_import_run,
        record_import_run_retry_summary,
        record_import_run_item,
    )
    from newspaper_translator.manage import run_cli
except ImportError:
    create_import_run = None
    finalize_import_run = None
    record_import_run_retry_summary = None
    record_import_run_item = None
    run_pending_migrations = None
    run_cli = None


class ManagementCommandTests(unittest.TestCase):
    def test_gmail_import_command_uses_config_file_and_reports_summary(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = pathlib.Path(temp_dir) / "gmail-config.json"
            config_path.write_text("{}")

            with patch("newspaper_translator.manage.import_from_gmail") as import_from_gmail:
                import_from_gmail.return_value = SimpleNamespace(
                    fetched_message_count=3,
                    imported_attachment_count=2,
                    created_document_count=1,
                    skipped_document_count=1,
                )

                exit_code, output = run_cli(
                    [
                        "gmail-import",
                        "--gmail-config",
                        str(config_path),
                        "--database-url",
                        "sqlite:////tmp/newspaper-translator.db",
                        "--storage-root",
                        "/tmp/newspaper-translator-data",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn('"fetched_message_count": 3', output)
        self.assertIn('"created_document_count": 1', output)

    def test_gmail_retry_failures_command_uses_config_file_and_reports_summary(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = pathlib.Path(temp_dir) / "gmail-config.json"
            config_path.write_text("{}")

            with patch("newspaper_translator.manage.retry_failed_gmail_messages") as retry_failed_gmail_messages:
                retry_failed_gmail_messages.return_value = SimpleNamespace(
                    run_id="retry-run-1",
                    retried_message_count=2,
                    resolved_message_count=1,
                    failed_final_message_count=1,
                )

                exit_code, output = run_cli(
                    [
                        "gmail-retry-failures",
                        "--gmail-config",
                        str(config_path),
                        "--database-url",
                        "sqlite:////tmp/newspaper-translator.db",
                        "--storage-root",
                        "/tmp/newspaper-translator-data",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn('"run_id": "retry-run-1"', output)
        self.assertIn('"retried_message_count": 2', output)

    def test_phase_3_parse_pdf_command_uses_mineru_entry_and_reports_articles(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            output_root = pathlib.Path(temp_dir) / "phase3-output"

            with patch.dict(
                "os.environ",
                {
                    "MINERU_API_TOKEN": "mineru-token",
                    "DEEPSEEK_API_KEY": "deepseek-key",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.MineruClient") as mineru_client_class:
                    mineru_client_class.return_value = SimpleNamespace(name="mineru-client")
                    with patch("newspaper_translator.manage.DeepSeekContinuationMatcher"):
                        with patch("newspaper_translator.manage.parse_pdf_articles") as parse_pdf_articles:
                            parse_pdf_articles.return_value = [
                                SimpleNamespace(
                                    page_number=1,
                                    x=0.0,
                                    y_top=1.0,
                                    title="talks to acquire Kelonia",
                                    body_text="Therapeutics for more than $2 billion.",
                                )
                            ]

                            exit_code, output = run_cli(
                                [
                                    "phase3-parse-pdf",
                                    "--pdf-path",
                                    str(pdf_path),
                                    "--output-root",
                                    str(output_root),
                                ]
                            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"title": "talks to acquire Kelonia"', output)
        self.assertIn('"body_text": "Therapeutics for more than $2 billion."', output)

    def test_phase_3_parse_md_command_reads_markdown_file_and_reports_articles(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = pathlib.Path(temp_dir) / "full.md"
            markdown_path.write_text(
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "Exxon, Chevron and others turn to Africa and South America for next prospects\n\n"
                "# BY COLLIN EATON\n\n"
                "Exxon Mobil, Chevron and other energy companies are speeding up their searches.\n",
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEY": "deepseek-key",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.DeepSeekContinuationMatcher"):
                    exit_code, output = run_cli(
                        [
                            "phase3-parse-md",
                            "--markdown-path",
                            str(markdown_path),
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn('"title": "Big Oil Explores Farther Afield To Dodge Middle East Turmoil"', output)
        self.assertIn('"body_text": "Exxon, Chevron and others turn to Africa and South America for next prospects', output)
        self.assertIn('BY COLLIN EATON', output)

    def test_phase_3_parse_pdf_command_builds_gemini_matcher_when_token_is_present(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            output_root = pathlib.Path(temp_dir) / "phase3-output"

            with patch.dict(
                "os.environ",
                {
                    "MINERU_API_TOKEN": "mineru-token",
                    "DEEPSEEK_API_KEY": "deepseek-key",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.MineruClient") as mineru_client_class:
                    mineru_client_class.return_value = SimpleNamespace(name="mineru-client")
                    with patch("newspaper_translator.manage.DeepSeekContinuationMatcher") as matcher_class:
                        matcher_class.return_value = SimpleNamespace(name="deepseek-matcher")
                        with patch("newspaper_translator.manage.parse_pdf_articles") as parse_pdf_articles:
                            parse_pdf_articles.return_value = [
                                SimpleNamespace(
                                    page_number=1,
                                    x=0.0,
                                    y_top=1.0,
                                    title="talks to acquire Kelonia",
                                    body_text="Therapeutics for more than $2 billion.",
                                )
                            ]

                            exit_code, output = run_cli(
                                [
                                    "phase3-parse-pdf",
                                    "--pdf-path",
                                    str(pdf_path),
                                    "--output-root",
                                    str(output_root),
                                ]
                            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"title": "talks to acquire Kelonia"', output)
        self.assertEqual(matcher_class.call_count, 1)
        self.assertEqual(parse_pdf_articles.call_args.kwargs["continuation_matcher"].name, "deepseek-matcher")

    def test_phase_3_parse_md_command_builds_gemini_matcher_when_token_is_present(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = pathlib.Path(temp_dir) / "full.md"
            markdown_path.write_text(
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "Exxon, Chevron and others turn to Africa and South America for next prospects\n\n"
                "Please turn to page A7\n\n"
                "# Big Oil Explores Farther Out\n\n"
                "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n",
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "DEEPSEEK_API_KEY": "deepseek-key",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.DeepSeekContinuationMatcher") as matcher_class:
                    matcher_class.return_value = SimpleNamespace(name="deepseek-matcher")
                    with patch("newspaper_translator.manage.extract_articles_from_mineru_markdown") as extract_articles:
                        extract_articles.return_value = [
                            SimpleNamespace(
                                page_number=1,
                                x=0.0,
                                y_top=1.0,
                                title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                                body_text="Exxon, Chevron and others turn to Africa and South America for next prospects",
                            )
                        ]

                        exit_code, output = run_cli(
                            [
                                "phase3-parse-md",
                                "--markdown-path",
                                str(markdown_path),
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertIn('"title": "Big Oil Explores Farther Afield To Dodge Middle East Turmoil"', output)
        self.assertEqual(matcher_class.call_count, 1)
        self.assertEqual(extract_articles.call_args.kwargs["continuation_matcher"].name, "deepseek-matcher")

    def test_phase_3_persist_document_command_uses_article_pipeline_entry(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = pathlib.Path(temp_dir) / "phase3-output"

            with patch.dict(
                "os.environ",
                {
                    "MINERU_API_TOKEN": "mineru-token",
                    "DEEPSEEK_API_KEY": "deepseek-key",
                    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                    "DEEPSEEK_MODEL": "deepseek-chat",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.MineruClient") as mineru_client_class:
                    mineru_client_class.return_value = SimpleNamespace(name="mineru-client")
                    with patch("newspaper_translator.manage.DeepSeekContinuationMatcher"):
                        with patch("newspaper_translator.manage.persist_document_articles") as persist_document_articles:
                            persist_document_articles.return_value = SimpleNamespace(
                                parse_run_id="parse-run-1",
                                document_key="message-1:attachment-1:abc",
                                status="succeeded",
                                publication_date="2026-04-20",
                            )

                            exit_code, output = run_cli(
                                [
                                    "phase3-persist-document",
                                    "--document-key",
                                    "message-1:attachment-1:abc",
                                    "--database-url",
                                    "sqlite:////tmp/newspaper-translator.db",
                                    "--output-root",
                                    str(output_root),
                                ]
                            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"parse_run_id": "parse-run-1"', output)
        self.assertIn('"publication_date": "2026-04-20"', output)
        self.assertEqual(
            persist_document_articles.call_args.kwargs["document_key"],
            "message-1:attachment-1:abc",
        )

    def test_phase_3_latest_articles_command_lists_current_visible_articles(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.list_latest_document_articles") as list_latest_document_articles:
            list_latest_document_articles.return_value = [
                SimpleNamespace(
                    article_id="article-1",
                    parse_run_id="parse-run-1",
                    document_key="message-1:attachment-1:abc",
                    publication_date="2026-04-20",
                    article_order=1,
                    title_en="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text_en="The oil companies want to maximize their production.",
                )
            ]

            exit_code, output = run_cli(
                [
                    "phase3-latest-articles",
                    "--database-url",
                    "sqlite:////tmp/newspaper-translator.db",
                    "--document-key",
                    "message-1:attachment-1:abc",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"article_id": "article-1"', output)
        self.assertIn('"publication_date": "2026-04-20"', output)
        self.assertIn('"title_en": "Big Oil Explores Farther Afield To Dodge Middle East Turmoil"', output)

    def test_phase_3_enrich_article_command_calls_orchestration_and_reports_run(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-chat",
            },
            clear=False,
        ):
            with patch("newspaper_translator.manage.DeepSeekArticleEnricher") as enricher_class:
                enricher_class.return_value = SimpleNamespace(name="enricher")
                with patch("newspaper_translator.manage.enrich_article") as enrich_article:
                    enrich_article.return_value = SimpleNamespace(
                        enrichment_run_id="enrichment-run-1",
                        article_id="article-1",
                        parse_run_id="parse-run-1",
                        status="succeeded",
                        provider_name="deepseek",
                        model_name="deepseek-chat",
                        prompt_version="article-enrichment-v2",
                        input_hash="hash-1",
                        started_at="2026-04-28 10:00:00",
                        finished_at="2026-04-28 10:00:02",
                        error_message=None,
                    )

                    exit_code, output = run_cli(
                        [
                            "phase3-enrich-article",
                            "--article-id",
                            "article-1",
                            "--database-url",
                            "sqlite:////tmp/newspaper-translator.db",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn('"enrichment_run_id": "enrichment-run-1"', output)
        self.assertIn('"status": "succeeded"', output)
        self.assertEqual(enricher_class.call_count, 1)
        self.assertEqual(enrich_article.call_args.kwargs["article_id"], "article-1")
        self.assertEqual(enrich_article.call_args.kwargs["provider_name"], "deepseek")
        self.assertEqual(enrich_article.call_args.kwargs["enricher"].name, "enricher")

    def test_phase_3_latest_enrichment_command_reports_current_visible_result(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.get_latest_article_enrichment") as get_latest_article_enrichment:
            get_latest_article_enrichment.return_value = SimpleNamespace(
                enrichment_run_id="enrichment-run-1",
                article_id="article-1",
                parse_run_id="parse-run-1",
                status="partial",
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                input_hash="hash-1",
                translated_title_zh="大型石油公司远赴他处避开中东动荡",
                summary_zh=None,
                translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
                translation_status="succeeded",
                summary_status="failed",
                tagging_status="failed",
                tags=[],
                started_at="2026-04-28 10:00:00",
                finished_at="2026-04-28 10:00:02",
            )

            exit_code, output = run_cli(
                [
                    "phase3-latest-enrichment",
                    "--database-url",
                    "sqlite:////tmp/newspaper-translator.db",
                    "--article-id",
                    "article-1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"enrichment_run_id": "enrichment-run-1"', output)
        self.assertIn('"status": "partial"', output)
        self.assertIn('"translated_title_zh": "\\u5927\\u578b\\u77f3\\u6cb9\\u516c\\u53f8\\u8fdc\\u8d74\\u4ed6\\u5904\\u907f\\u5f00\\u4e2d\\u4e1c\\u52a8\\u8361"', output)

    def test_scheduler_run_once_command_runs_one_manual_scheduler_tick(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
                "STORAGE_ROOT": "/tmp/newspaper-translator-data",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "MINERU_API_TOKEN": "mineru-token",
                "GEMINI_TOKEN": "gemini-token",
            },
            clear=False,
        ):
            with patch("newspaper_translator.manage.build_run_scheduler_tick_from_env") as build_run_scheduler_tick_from_env:
                run_tick_calls: list[str] = []

                def run_tick(*, trigger_type: str) -> str:
                    run_tick_calls.append(trigger_type)
                    return "scheduler-run-1"

                build_run_scheduler_tick_from_env.return_value = run_tick

                exit_code, output = run_cli(
                    [
                        "scheduler-run-once",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_tick_calls, ["manual"])
        self.assertEqual(build_run_scheduler_tick_from_env.call_count, 1)
        self.assertIn('"scheduler_run_id": "scheduler-run-1"', output)
        self.assertIn('"trigger_type": "manual"', output)

    def test_process_pending_documents_command_runs_manual_document_batch_without_gmail_import(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
                "STORAGE_ROOT": "/tmp/newspaper-translator-data",
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                "MINERU_API_TOKEN": "mineru-token",
                "GEMINI_TOKEN": "gemini-token",
            },
            clear=False,
        ):
            with patch("newspaper_translator.manage.run_process_pending_documents_from_env") as run_process_pending_documents_from_env:
                run_process_pending_documents_from_env.return_value = SimpleNamespace(
                    scheduler_run_id="scheduler-run-2",
                    trigger_type="manual",
                    selected_document_count=2,
                    completed_document_count=2,
                    failed_document_count=0,
                    status="succeeded",
                    import_run_id=None,
                    error_message=None,
                )

                exit_code, output = run_cli(
                    [
                        "process-pending-documents",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_process_pending_documents_from_env.call_count, 1)
        self.assertIn('"scheduler_run_id": "scheduler-run-2"', output)
        self.assertIn('"selected_document_count": 2', output)
        self.assertIn('"import_run_id": null', output)

    def test_process_pending_documents_uses_processing_tick_without_gmail_import(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.build_process_one_document_from_env") as build_document:
            with patch("newspaper_translator.manage.run_processing_tick") as run_processing_tick:
                build_document.return_value = lambda **kwargs: None
                run_processing_tick.return_value = SimpleNamespace(
                    scheduler_run_id="processing-run-1",
                    status="succeeded",
                    trigger_type="processing",
                )

                exit_code, output = run_cli(
                    [
                        "process-pending-documents",
                        "--database-url",
                        "sqlite:////tmp/newspaper-translator.db",
                    ]
                )

        payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["scheduler_run_id"], "processing-run-1")
        self.assertEqual(run_processing_tick.call_args.kwargs["trigger_type"], "processing")
        self.assertNotIn("import_documents", run_processing_tick.call_args.kwargs)
        self.assertNotIn("process_one_article", run_processing_tick.call_args.kwargs)

    def test_retry_document_command_requests_manual_retry_for_document(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.request_manual_document_retry") as request_manual_document_retry:
            request_manual_document_retry.return_value = SimpleNamespace(
                processing_run_id="processing-run-1",
                scheduler_run_id="scheduler-run-1",
                document_key="message-1:attachment-1:hash-1",
                status="manual_retry_requested",
                current_step="enrich",
                automatic_failure_count=2,
                last_failure_step="enrich",
                last_error_message="gemini timeout",
            )

            exit_code, output = run_cli(
                [
                    "retry-document",
                    "--database-url",
                    "sqlite:////tmp/newspaper-translator.db",
                    "--document-key",
                    "message-1:attachment-1:hash-1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(request_manual_document_retry.call_count, 1)
        self.assertEqual(
            request_manual_document_retry.call_args.kwargs["document_key"],
            "message-1:attachment-1:hash-1",
        )
        self.assertIn('"status": "manual_retry_requested"', output)
        self.assertIn('"automatic_failure_count": 2', output)

    def test_document_processing_status_command_returns_current_document_state(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.get_document_processing_run") as get_document_processing_run:
            get_document_processing_run.return_value = SimpleNamespace(
                processing_run_id="processing-run-1",
                scheduler_run_id="scheduler-run-1",
                document_key="message-1:attachment-1:hash-1",
                status="failed_retryable",
                current_step="parse_persist",
                automatic_failure_count=1,
                last_failure_step="parse_persist",
                last_error_message="mineru timeout",
            )

            exit_code, output = run_cli(
                [
                    "document-processing-status",
                    "--database-url",
                    "sqlite:////tmp/newspaper-translator.db",
                    "--document-key",
                    "message-1:attachment-1:hash-1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(get_document_processing_run.call_count, 1)
        self.assertEqual(
            get_document_processing_run.call_args.kwargs["document_key"],
            "message-1:attachment-1:hash-1",
        )
        self.assertIn('"status": "failed_retryable"', output)
        self.assertIn('"last_error_message": "mineru timeout"', output)

    def test_retry_article_command_requests_manual_retry_for_article(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.request_manual_article_retry") as request_manual_article_retry:
            request_manual_article_retry.return_value = SimpleNamespace(
                article_processing_run_id="article-processing-run-1",
                article_key="article-key-1",
                article_id="article-1",
                status="manual_retry_requested",
                current_step="completed",
                automatic_failure_count=1,
                last_error_message="summary timeout",
            )

            exit_code, output = run_cli(
                [
                    "retry-article",
                    "--database-url",
                    "sqlite:////tmp/newspaper-translator.db",
                    "--article-key",
                    "article-key-1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(request_manual_article_retry.call_count, 1)
        self.assertEqual(
            request_manual_article_retry.call_args.kwargs["article_key"],
            "article-key-1",
        )
        self.assertIn('"status": "manual_retry_requested"', output)
        self.assertIn('"article_key": "article-key-1"', output)

    def test_article_processing_status_command_returns_current_article_state(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with patch("newspaper_translator.manage.get_article_processing_run") as get_article_processing_run:
            get_article_processing_run.return_value = SimpleNamespace(
                article_processing_run_id="article-processing-run-1",
                article_key="article-key-1",
                article_id="article-1",
                status="failed_retryable",
                current_step="enrich",
                automatic_failure_count=1,
                last_error_message="summary timeout",
            )

            exit_code, output = run_cli(
                [
                    "article-processing-status",
                    "--database-url",
                    "sqlite:////tmp/newspaper-translator.db",
                    "--article-key",
                    "article-key-1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(get_article_processing_run.call_count, 1)
        self.assertEqual(
            get_article_processing_run.call_args.kwargs["article_key"],
            "article-key-1",
        )
        self.assertIn('"status": "failed_retryable"', output)
        self.assertIn('"last_error_message": "summary timeout"', output)

    def test_check_command_can_read_runtime_settings_from_environment(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            with patch.dict(
                "os.environ",
                {
                    "APP_ENV": "test",
                    "DATABASE_URL": database_url,
                    "STORAGE_ROOT": temp_dir,
                    "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
                },
                clear=False,
            ):
                exit_code, output = run_cli(["check", "--service", "worker"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"service": "worker"', output)
        self.assertIn('"status": "ok"', output)

    def test_check_command_reports_runtime_readiness_for_named_service(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            exit_code, output = run_cli(
                [
                    "check",
                    "--service",
                    "web",
                    "--app-env",
                    "test",
                    "--database-url",
                    database_url,
                    "--storage-root",
                    temp_dir,
                    "--gmail-config-path",
                    "/tmp/gmail-config.json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"service": "web"', output)
        self.assertIn('"status": "ok"', output)
        self.assertIn('"driver": "sqlite"', output)

    def test_migrate_command_applies_pending_migrations_and_reports_versions(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"

            exit_code, output = run_cli(
                [
                    "migrate",
                    "--database-url",
                    database_url,
                ]
            )
            self.assertTrue(database_path.exists())

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied migrations: 0001_initial", output)

    def test_gmail_import_runs_command_lists_recent_runs(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_import_run)
        self.assertIsNotNone(finalize_import_run)
        self.assertIsNotNone(record_import_run_retry_summary)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=run.run_id,
                fetched_message_count=2,
                imported_attachment_count=1,
                created_document_count=1,
                skipped_document_count=0,
            )
            record_import_run_retry_summary(
                database_url=database_url,
                run_id=run.run_id,
                retry_run_id="retry-run-1",
                retried_message_count=2,
                resolved_message_count=1,
                failed_final_message_count=1,
            )

            exit_code, output = run_cli(
                [
                    "gmail-import-runs",
                    "--database-url",
                    database_url,
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(run.run_id, output)
        self.assertIn('"status": "succeeded"', output)
        self.assertIn('"fetched_message_count": 2', output)
        self.assertIn('"retry_performed": true', output)
        self.assertIn('"retry_run_id": "retry-run-1"', output)
        self.assertIn('"retried_message_count": 2', output)
        self.assertIn('"resolved_message_count": 1', output)
        self.assertIn('"failed_final_message_count": 1', output)

    def test_gmail_import_run_items_command_lists_filtered_items(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_import_run)
        self.assertIsNotNone(record_import_run_item)
        self.assertIsNotNone(finalize_import_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=run.run_id,
                item_type="attachment",
                item_key="message:1:attachment:1",
                message_id="message-1",
                attachment_id="attachment-1",
                link_url=None,
                status="succeeded",
                detail_code="document_created",
                detail_message="Attachment imported.",
                document_key="message-1:attachment-1:abc",
            )
            record_import_run_item(
                database_url=database_url,
                run_id=run.run_id,
                item_type="body_link",
                item_key="message:1:body_link:https://example.com/bad",
                message_id="message-1",
                attachment_id=None,
                link_url="https://example.com/bad",
                status="failed",
                detail_code="link_fetch_failed",
                detail_message="Upstream SSL failure.",
                document_key=None,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=run.run_id,
                fetched_message_count=1,
                imported_attachment_count=1,
                created_document_count=1,
                skipped_document_count=0,
            )

            exit_code, output = run_cli(
                [
                    "gmail-import-run-items",
                    "--database-url",
                    database_url,
                    "--run-id",
                    run.run_id,
                    "--status",
                    "failed",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn('"item_type": "body_link"', output)
        self.assertIn('"detail_code": "link_fetch_failed"', output)
        self.assertNotIn('"item_type": "attachment"', output)

    def test_gmail_import_items_command_lists_recent_failed_items(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_import_run)
        self.assertIsNotNone(record_import_run_item)
        self.assertIsNotNone(finalize_import_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            first_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:7d",
                allowed_senders=["briefing@example.com"],
                max_results=25,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=first_run.run_id,
                item_type="body_link",
                item_key="message:1:body_link:https://example.com/bad-1",
                message_id="message-1",
                attachment_id=None,
                link_url="https://example.com/bad-1",
                status="failed",
                detail_code="link_fetch_failed",
                detail_message="First failure.",
                document_key=None,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=first_run.run_id,
                fetched_message_count=1,
                imported_attachment_count=0,
                created_document_count=0,
                skipped_document_count=0,
            )

            second_run = create_import_run(
                database_url=database_url,
                source_name="gmail",
                query="newer_than:1d",
                allowed_senders=["briefing@example.com"],
                max_results=10,
            )
            record_import_run_item(
                database_url=database_url,
                run_id=second_run.run_id,
                item_type="body_link",
                item_key="message:2:body_link:https://example.com/bad-2",
                message_id="message-2",
                attachment_id=None,
                link_url="https://example.com/bad-2",
                status="failed",
                detail_code="link_fetch_failed",
                detail_message="Second failure.",
                document_key=None,
            )
            finalize_import_run(
                database_url=database_url,
                run_id=second_run.run_id,
                fetched_message_count=1,
                imported_attachment_count=0,
                created_document_count=0,
                skipped_document_count=0,
            )

            exit_code, output = run_cli(
                [
                    "gmail-import-items",
                    "--database-url",
                    database_url,
                    "--status",
                    "failed",
                    "--item-type",
                    "body_link",
                    "--limit",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(second_run.run_id, output)
        self.assertIn("Second failure.", output)
        self.assertNotIn("First failure.", output)


    def test_phase3_parse_economist_pdf_outputs_articles_json(self) -> None:
        self.assertIsNotNone(
            run_cli,
            "run_cli should be importable from newspaper_translator.manage",
        )

        from newspaper_translator.economist_edition import (
            EditionArticle,
            ParsedEdition,
            build_economist_parse_result,
        )

        edition = ParsedEdition(
            parse_result=build_economist_parse_result(
                [
                    EditionArticle(
                        title="The World Cup paradox", section="Leaders",
                        start_page=17, end_page=23, body_text="Body.",
                        url="https://www.economist.com/leaders/2026/06/10/paradox",
                    )
                ]
            ),
            debug_text="debug",
        )

        with patch(
            "newspaper_translator.manage.parse_economist_edition",
            return_value=edition,
        ):
            exit_code, output = run_cli(
                ["phase3-parse-economist-pdf", "--pdf-path", "/tmp/te.pdf"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("The World Cup paradox", output)


if __name__ == "__main__":
    unittest.main()
