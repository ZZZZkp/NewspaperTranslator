import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.ingestion import (
        GmailAttachment,
        GmailMessage,
        create_document_processing_task,
        select_target_messages,
    )
except ImportError:
    GmailAttachment = None
    GmailMessage = None
    create_document_processing_task = None
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


if __name__ == "__main__":
    unittest.main()
