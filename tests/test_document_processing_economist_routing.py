import pathlib
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator import document_processing


class _StubMineru:
    pass


class EconomistRoutingTests(unittest.TestCase):
    def test_routes_economist_edition_to_local_persist(self) -> None:
        document = document_processing.StoredDocument(
            document_key="doc-key",
            original_filename="TE-2026-06-13-PDF_WEB.pdf",
            raw_path="/tmp/TE-2026-06-13-PDF_WEB.pdf",
            source_message_internal_date=None,
        )
        callback = document_processing._build_parse_persist_callback(
            database_url="sqlite:////tmp/does-not-matter.db",
            output_root="/tmp/out",
            mineru_client=_StubMineru(),
            continuation_matcher=None,
            parser_name="mineru",
            parser_version="vlm",
            continuation_matcher_name="deepseek",
            continuation_matcher_version="deepseek-chat",
        )

        with patch.object(document_processing, "_get_document", return_value=document), \
             patch.object(document_processing, "detect_calibre_economist_edition", return_value=True) as detect, \
             patch.object(document_processing, "persist_economist_edition_articles") as economist_persist, \
             patch.object(document_processing, "persist_document_articles") as mineru_persist:
            callback(document_key="doc-key")

        detect.assert_called_once()
        economist_persist.assert_called_once()
        mineru_persist.assert_not_called()

    def test_routes_other_pdf_to_mineru(self) -> None:
        document = document_processing.StoredDocument(
            document_key="doc-key",
            original_filename="wsj-2026-04-20.pdf",
            raw_path="/tmp/wsj.pdf",
            source_message_internal_date=None,
        )
        callback = document_processing._build_parse_persist_callback(
            database_url="sqlite:////tmp/does-not-matter.db",
            output_root="/tmp/out",
            mineru_client=_StubMineru(),
            continuation_matcher=None,
            parser_name="mineru",
            parser_version="vlm",
            continuation_matcher_name="deepseek",
            continuation_matcher_version="deepseek-chat",
        )

        with patch.object(document_processing, "_get_document", return_value=document), \
             patch.object(document_processing, "detect_calibre_economist_edition", return_value=False), \
             patch.object(document_processing, "persist_economist_edition_articles") as economist_persist, \
             patch.object(document_processing, "persist_document_articles") as mineru_persist:
            callback(document_key="doc-key")

        mineru_persist.assert_called_once()
        economist_persist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
