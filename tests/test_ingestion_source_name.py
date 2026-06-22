import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.ingestion import _extract_source_name_from_filename


class ExtractSourceNameTests(unittest.TestCase):
    def test_economist_eedition_filename_maps_to_economist_label(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("TE-2026-06-13-PDF_WEB.pdf"),
            "经济学人",
        )

    def test_translated_economist_eedition_also_maps_to_economist_label(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("【译】TE-2026-06-13-PDF_WEB.pdf"),
            "经济学人",
        )

    def test_ordinary_dated_filename_keeps_prefix(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("金融时报-5-6.pdf"),
            "金融时报",
        )

    def test_te_prefixed_non_economist_filename_does_not_map_to_economist(self) -> None:
        # A TE-prefixed name that is not the PDF_WEB e-edition must fall through
        # to the normal prefix logic, not become 经济学人.
        self.assertEqual(
            _extract_source_name_from_filename("TE-summary-2026-06-13.pdf"),
            "TE-summary",
        )

    def test_economist_usa_written_date_filename_maps_to_economist(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("The Economist USA - June 20 2026.pdf"),
            "经济学人",
        )

    def test_bloomberg_filename_maps_to_label(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("Bloomberg Businessweek USA - June 2026.pdf"),
            "彭博商业周刊",
        )


if __name__ == "__main__":
    unittest.main()
