import pathlib
import sqlite3
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.ingestion import (
        GmailAttachment,
        GmailMessage,
        create_document_processing_task,
        import_selected_messages,
        import_gmail_pdf_attachment,
        select_target_messages,
    )
except ImportError:
    run_pending_migrations = None
    GmailAttachment = None
    GmailMessage = None
    create_document_processing_task = None
    import_selected_messages = None
    import_gmail_pdf_attachment = None
    select_target_messages = None


class IngestionSelectionTests(unittest.TestCase):
    def test_selects_only_messages_from_configured_senders_with_pdf_attachments(self) -> None:
        self.assertIsNotNone(
            GmailAttachment,
            "GmailAttachment should be importable from newspaper_translator.ingestion",
        )
        self.assertIsNotNone(
            GmailMessage,
            "GmailMessage should be importable from newspaper_translator.ingestion",
        )
        self.assertIsNotNone(
            select_target_messages,
            "select_target_messages should be importable from newspaper_translator.ingestion",
        )

        matching_message = GmailMessage(
            message_id="message-1",
            sender="briefing@example.com",
            attachments=[
                GmailAttachment(
                    attachment_id="attachment-1",
                    filename="daily-paper.pdf",
                    mime_type="application/pdf",
                )
            ],
        )
        wrong_sender_message = GmailMessage(
            message_id="message-2",
            sender="other@example.com",
            attachments=[
                GmailAttachment(
                    attachment_id="attachment-2",
                    filename="daily-paper.pdf",
                    mime_type="application/pdf",
                )
            ],
        )
        no_pdf_message = GmailMessage(
            message_id="message-3",
            sender="briefing@example.com",
            attachments=[
                GmailAttachment(
                    attachment_id="attachment-3",
                    filename="daily-paper.txt",
                    mime_type="text/plain",
                )
            ],
        )

        selected = select_target_messages(
            messages=[matching_message, wrong_sender_message, no_pdf_message],
            allowed_senders={"briefing@example.com"},
        )

        self.assertEqual(selected, [matching_message])

    def test_creates_a_pending_document_processing_task_after_a_successful_import(self) -> None:
        self.assertIsNotNone(
            create_document_processing_task,
            "create_document_processing_task should be importable from newspaper_translator.ingestion",
        )

        task = create_document_processing_task(document_key="message-1:attachment-1:sha256:abc123")

        self.assertEqual(task.task_name, "process-document:message-1:attachment-1:sha256:abc123")
        self.assertEqual(task.status, "pending")

    def test_imports_a_pdf_attachment_into_raw_storage_and_document_metadata(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_gmail_pdf_attachment,
            "import_gmail_pdf_attachment should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[],
            )
            attachment = GmailAttachment(
                attachment_id="attachment-1",
                filename="daily-paper.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 sample content",
            )

            result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_document = connection.execute(
                    """
                    SELECT
                        source_name,
                        source_message_id,
                        source_attachment_id,
                        sender,
                        original_filename,
                        content_hash,
                        raw_path,
                        import_status
                    FROM documents
                    WHERE document_key = ?
                    """,
                    (result.document_key,),
                ).fetchone()
                stored_task = connection.execute(
                    """
                    SELECT task_name, status
                    FROM processing_tasks
                    WHERE task_name = ?
                    """,
                    (f"process-document:{result.document_key}",),
                ).fetchone()
            finally:
                connection.close()

            self.assertTrue(result.raw_path.exists())
            self.assertEqual(result.raw_path.read_bytes(), b"%PDF-1.7 sample content")

        self.assertTrue(result.was_created)
        self.assertEqual(
            stored_document,
            (
                "gmail",
                "message-1",
                "attachment-1",
                "briefing@example.com",
                "daily-paper.pdf",
                result.content_hash,
                str(result.raw_path),
                "imported",
            ),
        )
        self.assertEqual(
            stored_task,
            (f"process-document:{result.document_key}", "pending"),
        )

    def test_skips_duplicate_pdf_imports_for_the_same_attachment_payload(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_gmail_pdf_attachment,
            "import_gmail_pdf_attachment should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[],
            )
            attachment = GmailAttachment(
                attachment_id="attachment-1",
                filename="daily-paper.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 sample content",
            )

            first_result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )
            second_result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
                task_count = connection.execute(
                    "SELECT COUNT(*) FROM processing_tasks"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertTrue(first_result.was_created)
        self.assertFalse(second_result.was_created)
        self.assertEqual(first_result.document_key, second_result.document_key)
        self.assertEqual(first_result.raw_path, second_result.raw_path)
        self.assertEqual(document_count, 1)
        self.assertEqual(task_count, 1)

    def test_import_selected_messages_persists_only_matching_pdf_attachments(self) -> None:
        self.assertIsNotNone(
            run_pending_migrations,
            "run_pending_migrations should be importable from newspaper_translator.database",
        )
        self.assertIsNotNone(
            import_selected_messages,
            "import_selected_messages should be importable from newspaper_translator.ingestion",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            matching_message = GmailMessage(
                message_id="message-1",
                sender="briefing@example.com",
                attachments=[
                    GmailAttachment(
                        attachment_id="attachment-1",
                        filename="daily-paper.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 first",
                    ),
                    GmailAttachment(
                        attachment_id="attachment-2",
                        filename="notes.txt",
                        mime_type="text/plain",
                        content_bytes=b"not a pdf",
                    ),
                ],
            )
            wrong_sender_message = GmailMessage(
                message_id="message-2",
                sender="other@example.com",
                attachments=[
                    GmailAttachment(
                        attachment_id="attachment-3",
                        filename="other-paper.pdf",
                        mime_type="application/pdf",
                        content_bytes=b"%PDF-1.7 second",
                    )
                ],
            )

            results = import_selected_messages(
                messages=[matching_message, wrong_sender_message],
                allowed_senders={"briefing@example.com"},
                storage_root=storage_root,
                database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].document_key, "message-1:attachment-1:" + results[0].content_hash)
        self.assertEqual(document_count, 1)


if __name__ == "__main__":
    unittest.main()
