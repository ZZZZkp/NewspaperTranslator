import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.filename_metadata import (
    extract_filename_date,
    match_publisher_alias,
)


class MatchPublisherAliasTests(unittest.TestCase):
    def test_economist_usa_prefix_maps_to_economist(self) -> None:
        self.assertEqual(
            match_publisher_alias("The Economist USA - June 20 2026"),
            "经济学人",
        )

    def test_bare_economist_prefix_maps_to_economist(self) -> None:
        self.assertEqual(match_publisher_alias("The Economist - June 20 2026"), "经济学人")

    def test_bloomberg_prefix_maps_to_label(self) -> None:
        self.assertEqual(
            match_publisher_alias("Bloomberg Businessweek USA - June 2026"),
            "彭博商业周刊",
        )

    def test_unknown_prefix_returns_none(self) -> None:
        self.assertIsNone(match_publisher_alias("金融时报-5-6"))

    def test_longest_matching_alias_wins(self) -> None:
        from unittest import mock
        import newspaper_translator.filename_metadata as fm
        with mock.patch.dict(
            fm.PUBLISHER_ALIASES,
            {"acme": "SHORT", "acme weekly": "LONG"},
            clear=True,
        ):
            self.assertEqual(fm.match_publisher_alias("ACME Weekly - June 2026"), "LONG")
            self.assertEqual(fm.match_publisher_alias("ACME Daily"), "SHORT")


class ExtractFilenameDateTests(unittest.TestCase):
    def test_iso_date(self) -> None:
        self.assertEqual(extract_filename_date("wsj-2026-05-06.pdf"), "2026-05-06")

    def test_written_date_with_day(self) -> None:
        self.assertEqual(
            extract_filename_date("The Economist USA - June 20 2026.pdf"),
            "2026-06-20",
        )

    def test_written_month_year_defaults_to_first(self) -> None:
        self.assertEqual(
            extract_filename_date("Bloomberg Businessweek USA - June 2026.pdf"),
            "2026-06-01",
        )

    def test_invalid_written_date_returns_empty(self) -> None:
        self.assertEqual(extract_filename_date("Paper - June 31 2026.pdf"), "")

    def test_month_day_uses_gmail_year(self) -> None:
        # 2026-05-07 in Asia/Shanghai
        self.assertEqual(
            extract_filename_date(
                "金融时报-5-6.pdf",
                source_message_internal_date="1778083200000",
            ),
            "2026-05-06",
        )

    def test_month_day_uses_fallback_year_without_gmail(self) -> None:
        self.assertEqual(
            extract_filename_date("金融时报-5-6.pdf", fallback_year=2024),
            "2024-05-06",
        )

    def test_sept_abbreviation_normalizes(self) -> None:
        self.assertEqual(
            extract_filename_date("Paper - Sept 5 2026.pdf"),
            "2026-09-05",
        )

    def test_non_numeric_internal_date_falls_back_to_year(self) -> None:
        self.assertEqual(
            extract_filename_date(
                "金融时报-5-6.pdf",
                source_message_internal_date="not-a-number",
                fallback_year=2024,
            ),
            "2024-05-06",
        )

    def test_no_date_returns_empty(self) -> None:
        self.assertEqual(extract_filename_date("daily-paper.pdf"), "")


if __name__ == "__main__":
    unittest.main()
