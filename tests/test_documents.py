import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.documents import DocumentIdentity
except ImportError:
    DocumentIdentity = None


class DocumentIdentityTests(unittest.TestCase):
    def test_builds_a_stable_document_key_from_message_id_attachment_id_and_content_hash(self) -> None:
        self.assertIsNotNone(
            DocumentIdentity,
            "DocumentIdentity should be importable from newspaper_translator.documents",
        )

        identity = DocumentIdentity.from_attachment(
            message_id="gmail-message-123",
            attachment_id="attachment-456",
            content_hash="sha256:abc123",
        )

        self.assertEqual(identity.message_id, "gmail-message-123")
        self.assertEqual(identity.attachment_id, "attachment-456")
        self.assertEqual(identity.content_hash, "sha256:abc123")
        self.assertEqual(
            identity.document_key,
            "gmail-message-123:attachment-456:sha256:abc123",
        )

    def test_same_attachment_fields_produce_the_same_document_key(self) -> None:
        self.assertIsNotNone(
            DocumentIdentity,
            "DocumentIdentity should be importable from newspaper_translator.documents",
        )

        first = DocumentIdentity.from_attachment(
            message_id="gmail-message-123",
            attachment_id="attachment-456",
            content_hash="sha256:abc123",
        )
        second = DocumentIdentity.from_attachment(
            message_id="gmail-message-123",
            attachment_id="attachment-456",
            content_hash="sha256:abc123",
        )

        self.assertEqual(first.document_key, second.document_key)


if __name__ == "__main__":
    unittest.main()
