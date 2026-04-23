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
    from newspaper_translator.gmail import (
        build_gmail_service,
        import_from_gmail,
        load_gmail_integration_config,
    )
except ImportError:
    build_gmail_service = None
    run_pending_migrations = None
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


class _FakeGmailService:
    def users(self):
        return _FakeUsersResource()


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


if __name__ == "__main__":
    unittest.main()
