import base64
import json
import pathlib
import requests
import sqlite3
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
        get_import_checkpoint,
        get_import_run,
        list_failed_messages_for_retry,
        list_import_run_items,
        list_import_runs,
        set_import_checkpoint,
    )
    from newspaper_translator.gmail import (
        build_gmail_service,
        import_from_gmail,
        load_gmail_integration_config,
    )
except ImportError:
    build_gmail_service = None
    get_import_checkpoint = None
    get_import_run = None
    list_failed_messages_for_retry = None
    list_import_run_items = None
    list_import_runs = None
    run_pending_migrations = None
    set_import_checkpoint = None
    import_from_gmail = None
    load_gmail_integration_config = None


class GmailIntegrationTests(unittest.TestCase):
    def test_loads_gmail_integration_config_from_json_file(self) -> None:
        self.assertIsNotNone(
            load_gmail_integration_config,
            "load_gmail_integration_config should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            config_path = config_dir / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "has:attachment filename:pdf newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 25,
                        "include_spam_trash": False,
                    }
                )
            )

            config = load_gmail_integration_config(config_path)

        self.assertEqual(
            config.oauth_client_secrets_path,
            (config_dir / "secrets" / "google-client.json").resolve(),
        )
        self.assertEqual(
            config.oauth_token_path,
            (config_dir / "secrets" / "gmail-token.json").resolve(),
        )
        self.assertEqual(config.allowed_senders, ["briefing@example.com"])
        self.assertEqual(config.query, "has:attachment filename:pdf newer_than:7d")
        self.assertEqual(config.label_ids, ["INBOX"])
        self.assertEqual(config.max_results, 25)
        self.assertFalse(config.include_spam_trash)
        self.assertEqual(
            config.scopes,
            ["https://www.googleapis.com/auth/gmail.readonly"],
        )
        self.assertIsNone(config.proxy_url)

    def test_loads_optional_proxy_url_from_json_file(self) -> None:
        self.assertIsNotNone(
            load_gmail_integration_config,
            "load_gmail_integration_config should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            config_path = config_dir / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "proxy_url": "http://127.0.0.1:7897",
                    }
                )
            )

            config = load_gmail_integration_config(config_path)

        self.assertEqual(config.proxy_url, "http://127.0.0.1:7897")

    def test_build_gmail_service_uses_configured_proxy_for_requests_session(self) -> None:
        self.assertIsNotNone(
            build_gmail_service,
            "build_gmail_service should be importable from newspaper_translator.gmail",
        )
        self.assertIsNotNone(
            load_gmail_integration_config,
            "load_gmail_integration_config should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = pathlib.Path(temp_dir)
            config_path = config_dir / "gmail-config.json"
            token_path = config_dir / "secrets" / "gmail-token.json"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text("{}")
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "proxy_url": "http://127.0.0.1:7897",
                    }
                )
            )
            config = load_gmail_integration_config(config_path)

            fake_credentials = _FakeCredentials(valid=True)
            fake_session = _FakeAuthorizedSession(
                responses=[
                    {
                        "messages": [{"id": "message-1", "threadId": "thread-1"}],
                        "resultSizeEstimate": 1,
                    }
                ]
            )

            with patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_file",
                return_value=fake_credentials,
            ), patch(
                "google.auth.transport.requests.AuthorizedSession",
                return_value=fake_session,
            ) as authorized_session_ctor:
                service = build_gmail_service(config)
                result = service.users().messages().list(
                    userId="me",
                    q="newer_than:7d",
                    maxResults=1,
                    includeSpamTrash=False,
                    labelIds=["INBOX"],
                ).execute()

        self.assertEqual(
            fake_session.proxies,
            {
                "http": "http://127.0.0.1:7897",
                "https": "http://127.0.0.1:7897",
            },
        )
        authorized_session_ctor.assert_called_once_with(fake_credentials)
        self.assertEqual(
            result,
            {
                "messages": [{"id": "message-1", "threadId": "thread-1"}],
                "resultSizeEstimate": 1,
            },
        )
        self.assertEqual(
            fake_session.calls,
            [
                (
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    {
                        "q": "newer_than:7d",
                        "maxResults": 1,
                        "includeSpamTrash": False,
                        "labelIds": ["INBOX"],
                    },
                    30,
                )
            ],
        )

    def test_imports_matching_gmail_pdf_attachments_into_existing_ingestion_pipeline(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "has:attachment filename:pdf",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeGmailService(),
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(summary.fetched_message_count, 2)
        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(summary.skipped_document_count, 0)
        self.assertEqual(document_count, 1)

    def test_import_keeps_audit_source_as_gmail_but_stores_filename_prefix_on_document(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(get_import_run)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "has:attachment filename:pdf",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeFinancialTimesGmailService(),
            )
            stored_run = get_import_run(
                database_url=database_url,
                run_id=summary.run_id,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_row = connection.execute(
                    """
                    SELECT source_name, original_filename, source_message_internal_date
                    FROM documents
                    """
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(stored_run.source_name, "gmail")
        self.assertEqual(
            document_row,
            ("金融时报", "金融时报-5-6.pdf", "1778083200000"),
        )

    def test_imports_pdf_documents_linked_from_message_bodies(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["example.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeGmailLinkService(),
                downloader=_FakeLinkDownloader(),
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(summary.fetched_message_count, 2)
        self.assertEqual(summary.imported_attachment_count, 2)
        self.assertEqual(summary.created_document_count, 2)
        self.assertEqual(summary.skipped_document_count, 0)
        self.assertEqual(document_count, 2)

    def test_skips_unreachable_body_links_and_imports_remaining_pdf_documents(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )
        self.assertIsNotNone(
            get_import_run,
            "get_import_run should be importable from newspaper_translator.import_audit",
        )
        self.assertIsNotNone(
            list_import_run_items,
            "list_import_run_items should be importable from newspaper_translator.import_audit",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": [],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeGmailMixedLinkService(),
                downloader=_FakeFlakyLinkDownloader(),
            )
            stored_run = get_import_run(
                database_url=database_url,
                run_id=summary.run_id,
            )
            failed_items = list_import_run_items(
                database_url=database_url,
                run_id=summary.run_id,
                status="failed",
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(summary.fetched_message_count, 1)
        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(summary.skipped_document_count, 0)
        self.assertEqual(summary.status, "partial")
        self.assertEqual(stored_run.status, "partial")
        self.assertEqual(stored_run.failed_item_count, 1)
        self.assertEqual([item.item_type for item in failed_items], ["body_link"])
        self.assertEqual([item.detail_code for item in failed_items], ["link_fetch_failed"])
        self.assertEqual(document_count, 1)

    def test_imports_direct_download_links_that_do_not_end_with_pdf(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["wx.mail.qq.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeGmailQqDownloadService(),
                downloader=_FakeQqDownloadLinkDownloader(),
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_row = connection.execute(
                    """
                    SELECT original_filename, raw_path
                    FROM documents
                    """
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(summary.fetched_message_count, 1)
        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(stored_row[0], "download.pdf")
        self.assertTrue(stored_row[1].endswith(".pdf"))

    def test_imports_pdf_documents_from_direct_download_urls_without_pdf_suffix(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["wx.mail.qq.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeQqMailLinkService(),
                downloader=_FakeQqMailDownloader(),
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(summary.fetched_message_count, 1)
        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(summary.skipped_document_count, 0)
        self.assertEqual(document_count, 1)

    def test_imports_pdf_documents_from_qq_mail_landing_pages_via_json_resolution(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["wx.mail.qq.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            downloader = _FakeQqMailLandingPageDownloader()
            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeQqMailLandingPageService(),
                downloader=downloader,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_row = connection.execute(
                    """
                    SELECT original_filename, raw_path
                    FROM documents
                    """
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(summary.fetched_message_count, 1)
        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(summary.skipped_document_count, 0)
        self.assertEqual(downloader.resolved_urls, ["https://wx.mail.qq.com/ftn/download?func=3&key=landing"])
        self.assertEqual(
            downloader.downloaded_urls,
            ["https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123"],
        )
        self.assertEqual(stored_row[0], "download.pdf")
        self.assertTrue(stored_row[1].endswith(".pdf"))

    def test_imports_long_signed_body_links_without_storing_the_full_url_as_attachment_identity(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        long_signed_url = (
            "https://www.dengtazk.xin:8282/api/public/email-download"
            "?attachmentId=1058"
            "&sentAt=1777637975"
            "&delayMinutes=1440"
            "&sign=3ad4d67f0172fefdb8e61497ba80dc0c80020edf28396447a55db10ec1df1453"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["www.dengtazk.xin"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeLongSignedLinkService(long_signed_url),
                downloader=_FakeLongSignedLinkDownloader(long_signed_url),
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_row = connection.execute(
                    """
                    SELECT source_attachment_id, original_filename, raw_path
                    FROM documents
                    """
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(stored_row[1], "email-download.pdf")
        self.assertNotEqual(stored_row[0], f"link:{long_signed_url}")
        self.assertNotIn("attachmentId=1058", stored_row[0])
        self.assertNotIn("attachmentId=1058", pathlib.Path(stored_row[2]).name)
        self.assertLess(len(pathlib.Path(stored_row[2]).name), 180)

    def test_imports_pdf_documents_from_dengtazk_preview_pages_via_script_resource_urls(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_from_gmail,
            "import_from_gmail should be importable from newspaper_translator.gmail",
        )

        preview_url = (
            "https://www.dengtazk.xin:8282/api/public/email-download"
            "?attachmentId=1066"
            "&sentAt=1777728107"
            "&delayMinutes=1440"
            "&sign=19095352459332b104d5b2f393bed594d9e2952617f16d43d1bbd2f9dfd077ac"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["www.dengtazk.xin"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeDengtazkPreviewPageService(preview_url),
                downloader=_FakeDengtazkPreviewPageDownloader(preview_url),
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_row = connection.execute(
                    """
                    SELECT original_filename, raw_path
                    FROM documents
                    """
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(stored_row[0], "preview-file.pdf")
        self.assertTrue(stored_row[1].endswith(".pdf"))

    def test_skips_translated_pdf_body_links_and_records_filtered_audit_items(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(list_import_run_items)

        translated_url = "https://example.com/pdfs/中文-华尔街日报-2026.pdf"
        regular_url = "https://example.com/pdfs/regular-paper.pdf"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["example.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeTranslatedBodyLinkService(translated_url, regular_url),
                downloader=_FakeTranslatedBodyLinkDownloader(translated_url, regular_url),
            )

            skipped_items = list_import_run_items(
                database_url=database_url,
                run_id=summary.run_id,
                status="skipped",
            )

        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        filtered_items = [
            item for item in skipped_items
            if item.detail_code == "body_link_filename_filtered"
        ]
        self.assertEqual(len(filtered_items), 1)
        self.assertEqual(filtered_items[0].link_url, translated_url)

    def test_skips_translation_prefix_pdf_body_links_and_records_filtered_audit_items(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(list_import_run_items)

        translated_url = "https://example.com/pdfs/【译】金融时报-5-5.pdf"
        regular_url = "https://example.com/pdfs/regular-paper.pdf"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["example.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeTranslatedBodyLinkService(translated_url, regular_url),
                downloader=_FakeTranslatedBodyLinkDownloader(translated_url, regular_url),
            )

            skipped_items = list_import_run_items(
                database_url=database_url,
                run_id=summary.run_id,
                status="skipped",
            )

        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        filtered_items = [
            item for item in skipped_items
            if item.detail_code == "body_link_filename_filtered"
        ]
        self.assertEqual(len(filtered_items), 1)
        self.assertEqual(filtered_items[0].link_url, translated_url)

    def test_skips_percent_encoded_translation_prefix_pdf_body_links(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(list_import_run_items)

        translated_url = (
            "https://example.com/pdfs/"
            "%E3%80%90%E8%AF%91%E3%80%91%E9%87%91%E8%9E%8D%E6%97%B6%E6%8A%A5-5-5.pdf"
        )
        regular_url = "https://example.com/pdfs/regular-paper.pdf"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["example.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeTranslatedBodyLinkService(translated_url, regular_url),
                downloader=_FakeTranslatedBodyLinkDownloader(translated_url, regular_url),
            )

            skipped_items = list_import_run_items(
                database_url=database_url,
                run_id=summary.run_id,
                status="skipped",
            )

        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        filtered_items = [
            item for item in skipped_items
            if item.detail_code == "body_link_filename_filtered"
        ]
        self.assertEqual(len(filtered_items), 1)
        self.assertEqual(filtered_items[0].link_url, translated_url)

    def test_marks_import_run_failed_when_gmail_fetch_aborts(self) -> None:
        self.assertIsNotNone(list_import_runs)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            with self.assertRaises(RuntimeError):
                import_from_gmail(
                    config_path=config_path,
                    storage_root=storage_root,
                    database_url=database_url,
                    service=_FailingGmailService(),
                )

            runs = list_import_runs(database_url=database_url, limit=10)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "failed")
        self.assertEqual(runs[0].fetched_message_count, 0)

    def test_uses_checkpoint_to_narrow_query_and_advance_processed_message_time(self) -> None:
        self.assertIsNotNone(set_import_checkpoint)
        self.assertIsNotNone(get_import_checkpoint)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "label:news newer_than:30d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            set_import_checkpoint(
                database_url=database_url,
                source_name="gmail",
                checkpoint_type="message_internal_date",
                checkpoint_value="1713820800000",
            )

            service = _CheckpointAwareGmailService()
            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=service,
            )
            updated_checkpoint = get_import_checkpoint(
                database_url=database_url,
                source_name="gmail",
                checkpoint_type="message_internal_date",
            )
            stored_run = get_import_run(
                database_url=database_url,
                run_id=summary.run_id,
            )

        self.assertIn("label:news newer_than:30d", service.list_queries[0])
        self.assertIn("after:1713820800", service.list_queries[0])
        self.assertEqual(updated_checkpoint, "1713907200000")
        self.assertEqual(stored_run.checkpoint_before, "1713820800000")
        self.assertEqual(stored_run.checkpoint_after, "1713907200000")

    def test_automatically_retries_pending_failed_messages_once(self) -> None:
        self.assertIsNotNone(list_failed_messages_for_retry)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["example.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            service = _RetryingSingleMessageService()
            downloader = _FlakyThenHealthyDownloader()
            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=service,
                downloader=downloader,
            )
            retryable_messages = list_failed_messages_for_retry(
                database_url=database_url,
                source_name="gmail",
            )
            stored_parent_run = get_import_run(
                database_url=database_url,
                run_id=summary.run_id,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
                failed_message_row = connection.execute(
                    """
                    SELECT retry_state, retry_attempt_count
                    FROM failed_messages
                    WHERE message_id = 'message-retry-1'
                    """
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(summary.status, "partial")
        self.assertEqual(document_count, 1)
        self.assertEqual(retryable_messages, [])
        self.assertEqual(failed_message_row, ("resolved", 1))
        self.assertTrue(summary.retry_performed)
        self.assertIsNotNone(summary.retry_run_id)
        self.assertEqual(summary.retried_message_count, 1)
        self.assertEqual(summary.resolved_message_count, 1)
        self.assertEqual(summary.failed_final_message_count, 0)
        self.assertTrue(stored_parent_run.retry_performed)
        self.assertIsNotNone(stored_parent_run.retry_run_id)
        self.assertEqual(stored_parent_run.retried_message_count, 1)
        self.assertEqual(stored_parent_run.resolved_message_count, 1)
        self.assertEqual(stored_parent_run.failed_final_message_count, 0)


class _FakeGmailService:
    def users(self):
        return _FakeUsersResource()


class _FailingGmailService:
    def users(self):
        return _FailingUsersResource()


class _FailingUsersResource:
    def messages(self):
        return _FailingMessagesResource()


class _FailingMessagesResource:
    def list(self, **kwargs):
        raise RuntimeError("gmail list failed")


class _CheckpointAwareGmailService:
    def __init__(self) -> None:
        self.list_queries: list[str] = []

    def users(self):
        return _CheckpointAwareUsersResource(self)


class _CheckpointAwareUsersResource:
    def __init__(self, service: "_CheckpointAwareGmailService") -> None:
        self._service = service

    def messages(self):
        return _CheckpointAwareMessagesResource(self._service)


class _CheckpointAwareMessagesResource:
    def __init__(self, service: "_CheckpointAwareGmailService") -> None:
        self._service = service

    def list(self, **kwargs):
        self._service.list_queries.append(kwargs["q"])
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-checkpoint-1", "threadId": "thread-checkpoint-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": "message-checkpoint-1",
                "internalDate": "1713907200000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "partId": "1",
                            "mimeType": "application/pdf",
                            "filename": "daily-paper.pdf",
                            "body": {"attachmentId": "attachment-checkpoint-1"},
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _CheckpointAwareAttachmentsResource()


class _CheckpointAwareAttachmentsResource:
    def get(self, *, userId: str, messageId: str, id: str):
        return _FakeRequest({"data": "JVBERi0xLjcgaW5jcmVtZW50YWw="})


class _FakeFinancialTimesGmailService:
    def users(self):
        return _FakeFinancialTimesUsersResource()


class _FakeFinancialTimesUsersResource:
    def messages(self):
        return _FakeFinancialTimesMessagesResource()


class _FakeFinancialTimesMessagesResource:
    def list(self, **_kwargs):
        return _FakeRequest(
            {"messages": [{"id": "ft-message-1", "threadId": "thread-1"}]}
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": id,
                "payload": {
                    "headers": [{"name": "From", "value": "briefing@example.com"}],
                    "parts": [
                        {
                            "filename": "金融时报-5-6.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "attachment-1"},
                        }
                    ],
                },
                "internalDate": "1778083200000",
            }
        )

    def attachments(self):
        return _FakeFinancialTimesAttachmentsResource()


class _FakeFinancialTimesAttachmentsResource:
    def get(self, *, userId: str, messageId: str, id: str):
        return _FakeRequest(
            {"data": base64.urlsafe_b64encode(b"%PDF-1.7 ft bytes").decode("ascii")}
        )


class _FakeUsersResource:
    def messages(self):
        return _FakeMessagesResource()


class _FakeMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-1", "threadId": "thread-1"},
                    {"id": "message-2", "threadId": "thread-2"},
                ],
                "resultSizeEstimate": 2,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        payloads = {
            "message-1": {
                "id": "message-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "partId": "1",
                            "mimeType": "application/pdf",
                            "filename": "daily-paper.pdf",
                            "body": {"attachmentId": "attachment-1"},
                        }
                    ],
                },
            },
            "message-2": {
                "id": "message-2",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Other <other@example.com>"}
                    ],
                    "parts": [
                        {
                            "partId": "1",
                            "mimeType": "application/pdf",
                            "filename": "other-paper.pdf",
                            "body": {"attachmentId": "attachment-2"},
                        }
                    ],
                },
            },
        }
        return _FakeRequest(payloads[id])

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeAttachmentsResource:
    def get(self, *, userId: str, messageId: str, id: str):
        attachments = {
            ("message-1", "attachment-1"): {
                "data": "JVBERi0xLjcgc2FtcGxlIGNvbnRlbnQ"
            },
            ("message-2", "attachment-2"): {
                "data": "JVBERi0xLjcgb3RoZXIgY29udGVudA"
            },
        }
        return _FakeRequest(attachments[(messageId, id)])


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeCredentials:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid
        self.expired = False
        self.refresh_token = None

    def to_json(self) -> str:
        return "{}"


class _FakeAuthorizedSession:
    def __init__(self, *, responses: list[dict[str, object]]) -> None:
        self.proxies: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, object] | None, int | None]] = []
        self._responses = list(responses)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, object] | None = None,
        timeout: int | None = None,
    ):
        self.calls.append((method, url, params, timeout))
        return _FakeHttpResponse(self._responses.pop(0))


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeGmailLinkService:
    def users(self):
        return _FakeLinkUsersResource()


class _FakeLinkUsersResource:
    def messages(self):
        return _FakeLinkMessagesResource()


class _FakeLinkMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-link-1", "threadId": "thread-1"},
                    {"id": "message-link-2", "threadId": "thread-2"},
                ],
                "resultSizeEstimate": 2,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        payloads = {
            "message-link-1": {
                "id": "message-link-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {
                                "data": "RGlyZWN0IGxpbmsgaHR0cHM6Ly9leGFtcGxlLmNvbS9wYXBlci90b2RheS5wZGY"
                            },
                        }
                    ],
                },
            },
            "message-link-2": {
                "id": "message-link-2",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/html",
                            "filename": "",
                            "body": {
                                "data": "PGEgaHJlZj0iaHR0cHM6Ly9leGFtcGxlLmNvbS9pc3N1ZS90b2RheSI-T3BlbiBwYXBlcjwvYT4"
                            },
                        }
                    ],
                },
            },
        }
        return _FakeRequest(payloads[id])

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeLinkDownloader:
    def download_binary(self, url: str) -> bytes:
        downloads = {
            "https://example.com/paper/today.pdf": b"%PDF-1.7 direct-link",
            "https://example.com/downloads/today-edition.pdf": b"%PDF-1.7 html-link",
        }
        return downloads[url]

    def fetch_html(self, url: str) -> str:
        pages = {
            "https://example.com/issue/today": """
                <html>
                  <body>
                    <a href="/downloads/today-edition.pdf">Download PDF</a>
                  </body>
                </html>
            """
        }
        return pages[url]


class _FakeGmailMixedLinkService:
    def users(self):
        return _FakeMixedLinkUsersResource()


class _FakeMixedLinkUsersResource:
    def messages(self):
        return _FakeMixedLinkMessagesResource()


class _FakeMixedLinkMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-mixed-1", "threadId": "thread-mixed-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": "message-mixed-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {
                                "data": "aHR0cHM6Ly9iYWQuZXhhbXBsZS5jb20vYnJva2VuIGh0dHBzOi8vZXhhbXBsZS5jb20vcGFwZXIvdG9kYXkucGRm"
                            },
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeFlakyLinkDownloader:
    def download_binary(self, url: str) -> bytes:
        if url == "https://example.com/paper/today.pdf":
            return b"%PDF-1.7 direct-link"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        if url == "https://bad.example.com/broken":
            raise requests.exceptions.SSLError("upstream ssl failure")
        raise AssertionError(f"Unexpected HTML fetch URL: {url}")


class _FakeGmailQqDownloadService:
    def users(self):
        return _FakeQqUsersResource()


class _FakeQqUsersResource:
    def messages(self):
        return _FakeQqMessagesResource()


class _FakeQqMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-qq-1", "threadId": "thread-qq-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": "message-qq-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {
                                "data": "aHR0cHM6Ly93eC5tYWlsLnFxLmNvbS9mdG4vZG93bmxvYWQ_ZnVuYz0zJmtleT1hYmMmZnJvbT0jLw"
                            },
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeQqDownloadLinkDownloader:
    def download_binary(self, url: str) -> bytes:
        return b"%PDF-1.7 qq-download-link"

    def fetch_html(self, url: str) -> str:
        raise AssertionError("Direct QQ download links should not be fetched as HTML first")


class _FakeQqMailLinkService:
    def users(self):
        return _FakeQqMailUsersResource()


class _FakeQqMailUsersResource:
    def messages(self):
        return _FakeQqMailMessagesResource()


class _FakeQqMailMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-qq-1", "threadId": "thread-qq-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        payload = {
            "id": "message-qq-1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Briefing <briefing@example.com>"}
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {
                            "data": "aHR0cHM6Ly93eC5tYWlsLnFxLmNvbS9mdG4vZG93bmxvYWQ_ZnVuYz0zJmtleT1hYmMmY29kZT0xMjM"
                        },
                    }
                ],
            },
        }
        return _FakeRequest(payload)

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeQqMailDownloader:
    def download_binary(self, url: str) -> bytes:
        if "wx.mail.qq.com/ftn/download" in url:
            return b"%PDF-1.7 qqmail-direct"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for direct QQ download URL: {url}")


class _FakeQqMailLandingPageService:
    def users(self):
        return _FakeQqMailLandingPageUsersResource()


class _FakeQqMailLandingPageUsersResource:
    def messages(self):
        return _FakeQqMailLandingPageMessagesResource()


class _FakeQqMailLandingPageMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-qq-landing-1", "threadId": "thread-qq-landing-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        payload = {
            "id": "message-qq-landing-1",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Briefing <briefing@example.com>"}
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {
                            "data": "aHR0cHM6Ly93eC5tYWlsLnFxLmNvbS9mdG4vZG93bmxvYWQ_ZnVuYz0zJmtleT1sYW5kaW5n"
                        },
                    }
                ],
            },
        }
        return _FakeRequest(payload)

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeQqMailLandingPageDownloader:
    def __init__(self) -> None:
        self.resolved_urls: list[str] = []
        self.downloaded_urls: list[str] = []

    def resolve_download_url(self, url: str) -> str | None:
        self.resolved_urls.append(url)
        if url == "https://wx.mail.qq.com/ftn/download?func=3&key=landing":
            return "https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123"
        return None

    def download_binary(self, url: str) -> bytes:
        self.downloaded_urls.append(url)
        if url == "https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123":
            return b"%PDF-1.7 qqmail-json"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for QQ landing page URL: {url}")


class _FakeLongSignedLinkService:
    def __init__(self, long_signed_url: str) -> None:
        self._long_signed_url = long_signed_url

    def users(self):
        return _FakeLongSignedLinkUsersResource(self._long_signed_url)


class _FakeLongSignedLinkUsersResource:
    def __init__(self, long_signed_url: str) -> None:
        self._long_signed_url = long_signed_url

    def messages(self):
        return _FakeLongSignedLinkMessagesResource(self._long_signed_url)


class _FakeLongSignedLinkMessagesResource:
    def __init__(self, long_signed_url: str) -> None:
        self._long_signed_url = long_signed_url

    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-long-link-1", "threadId": "thread-long-link-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": "message-long-link-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {
                                "data": _encode_gmail_body(self._long_signed_url)
                            },
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeLongSignedLinkDownloader:
    def __init__(self, long_signed_url: str) -> None:
        self._long_signed_url = long_signed_url

    def download_binary(self, url: str) -> bytes:
        if url != self._long_signed_url:
            raise AssertionError(f"Unexpected binary download URL: {url}")
        return b"%PDF-1.7 long-signed-link"

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for direct PDF URL: {url}")


class _FakeDengtazkPreviewPageService:
    def __init__(self, preview_url: str) -> None:
        self._preview_url = preview_url

    def users(self):
        return _FakeDengtazkPreviewPageUsersResource(self._preview_url)


class _FakeDengtazkPreviewPageUsersResource:
    def __init__(self, preview_url: str) -> None:
        self._preview_url = preview_url

    def messages(self):
        return _FakeDengtazkPreviewPageMessagesResource(self._preview_url)


class _FakeDengtazkPreviewPageMessagesResource:
    def __init__(self, preview_url: str) -> None:
        self._preview_url = preview_url

    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-preview-link-1", "threadId": "thread-preview-link-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": "message-preview-link-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {
                                "data": _encode_gmail_body(self._preview_url)
                            },
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeDengtazkPreviewPageDownloader:
    def __init__(self, preview_url: str) -> None:
        self._preview_url = preview_url
        self.downloaded_urls: list[str] = []

    def download_binary(self, url: str) -> bytes:
        self.downloaded_urls.append(url)
        if url == self._preview_url:
            return b"<html>preview shell</html>"
        if url == "https://www.dengtazk.xin:8282/files/preview-file.pdf":
            return b"%PDF-1.7 preview-file"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        if url != self._preview_url:
            raise AssertionError(f"Unexpected HTML fetch URL: {url}")
        return """
            <html>
              <body>
                <script>
                  window.viewerConfig = {
                    pdfUrl: "/files/preview-file.pdf"
                  };
                </script>
              </body>
            </html>
        """


class _RetryingSingleMessageService:
    def users(self):
        return _RetryingSingleMessageUsersResource()


class _RetryingSingleMessageUsersResource:
    def messages(self):
        return _RetryingSingleMessageMessagesResource()


class _RetryingSingleMessageMessagesResource:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-retry-1", "threadId": "thread-retry-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        return _FakeRequest(
            {
                "id": "message-retry-1",
                "internalDate": "1714000000000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {
                                "data": "aHR0cHM6Ly9leGFtcGxlLmNvbS9yZXRyeS1wYXBlci5wZGY="
                            },
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _FakeAttachmentsResource()


class _FlakyThenHealthyDownloader:
    def __init__(self) -> None:
        self._download_attempts: dict[str, int] = {}

    def download_binary(self, url: str) -> bytes:
        attempts = self._download_attempts.get(url, 0)
        self._download_attempts[url] = attempts + 1
        if attempts == 0:
            raise requests.exceptions.SSLError("temporary upstream failure")
        if url == "https://example.com/retry-paper.pdf":
            return b"%PDF-1.7 retry-success"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for direct PDF URL: {url}")


class _FakeTranslatedBodyLinkService:
    def __init__(self, translated_url: str, regular_url: str) -> None:
        self._translated_url = translated_url
        self._regular_url = regular_url

    def users(self):
        return _FakeTranslatedBodyLinkUsersResource(self._translated_url, self._regular_url)


class _FakeTranslatedBodyLinkUsersResource:
    def __init__(self, translated_url: str, regular_url: str) -> None:
        self._translated_url = translated_url
        self._regular_url = regular_url

    def messages(self):
        return _FakeTranslatedBodyLinkMessagesResource(self._translated_url, self._regular_url)


class _FakeTranslatedBodyLinkMessagesResource:
    def __init__(self, translated_url: str, regular_url: str) -> None:
        self._translated_url = translated_url
        self._regular_url = regular_url

    def list(self, **kwargs):
        return _FakeRequest(
            {
                "messages": [
                    {"id": "message-translated-link-1", "threadId": "thread-translated-1"},
                ],
                "resultSizeEstimate": 1,
            }
        )

    def get(self, *, userId: str, id: str, format: str):
        body_text = f"{self._translated_url} {self._regular_url}"
        return _FakeRequest(
            {
                "id": "message-translated-link-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Briefing <briefing@example.com>"}
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {"data": _encode_gmail_body(body_text)},
                        }
                    ],
                },
            }
        )

    def attachments(self):
        return _FakeAttachmentsResource()


class _FakeTranslatedBodyLinkDownloader:
    def __init__(self, translated_url: str, regular_url: str) -> None:
        self._translated_url = translated_url
        self._regular_url = regular_url

    def download_binary(self, url: str) -> bytes:
        if url == self._translated_url:
            return b"%PDF-1.7 translated-content"
        if url == self._regular_url:
            return b"%PDF-1.7 regular-content"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for direct PDF URLs: {url}")


def _encode_gmail_body(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


if __name__ == "__main__":
    unittest.main()
