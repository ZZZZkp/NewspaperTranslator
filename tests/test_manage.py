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
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.MineruClient") as mineru_client_class:
                    mineru_client_class.return_value = SimpleNamespace(name="mineru-client")
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
                    "GEMINI_TOKEN": "gemini-token",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.MineruClient") as mineru_client_class:
                    mineru_client_class.return_value = SimpleNamespace(name="mineru-client")
                    with patch("newspaper_translator.manage.GeminiContinuationMatcher") as matcher_class:
                        matcher_class.return_value = SimpleNamespace(name="gemini-matcher")
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
        self.assertEqual(parse_pdf_articles.call_args.kwargs["continuation_matcher"].name, "gemini-matcher")

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
                    "GEMINI_TOKEN": "gemini-token",
                },
                clear=False,
            ):
                with patch("newspaper_translator.manage.GeminiContinuationMatcher") as matcher_class:
                    matcher_class.return_value = SimpleNamespace(name="gemini-matcher")
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
        self.assertEqual(extract_articles.call_args.kwargs["continuation_matcher"].name, "gemini-matcher")

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


if __name__ == "__main__":
    unittest.main()
