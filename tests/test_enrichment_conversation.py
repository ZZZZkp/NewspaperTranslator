import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class _Article:
    title_en = "Big Oil Explores Farther Afield"
    body_text_en = "U.S. oil futures were trading near $90 a barrel Sunday."


class StepParsingTests(unittest.TestCase):
    def test_ad_judgment_message_includes_title_and_body(self) -> None:
        from newspaper_translator.enrichment_conversation import build_ad_judgment_message

        message = build_ad_judgment_message(_Article())
        self.assertIn("Big Oil Explores Farther Afield", message)
        self.assertIn("U.S. oil futures", message)

    def test_parse_ad_judgment_returns_type_and_reason(self) -> None:
        from newspaper_translator.enrichment_conversation import parse_ad_judgment

        self.assertEqual(
            parse_ad_judgment(
                {"content_type": "article", "classification_reason": "  normal  "}
            ),
            ("article", "normal"),
        )

    def test_parse_ad_judgment_rejects_bad_content_type(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_ad_judgment,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_ad_judgment({"content_type": "bogus", "classification_reason": ""})

    def test_parse_translation_requires_nonempty_for_article(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_translation,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_translation(
                {"translated_title_zh": "", "translated_body_zh": ""},
                content_type="article",
            )

    def test_parse_translation_allows_empty_for_advertisement(self) -> None:
        from newspaper_translator.enrichment_conversation import parse_translation

        self.assertEqual(
            parse_translation(
                {"translated_title_zh": "", "translated_body_zh": ""},
                content_type="advertisement",
            ),
            ("", ""),
        )

    def test_parse_summary_rejects_multiline(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_summary,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_summary({"summary_zh": "line one\nline two"})

    def test_parse_tags_normalizes_and_enforces_count(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_tags,
        )

        self.assertEqual(
            parse_tags({"tags": ["  经济  ", "经济", "市场", "企业"]}),
            ["经济", "市场", "企业"],
        )
        with self.assertRaises(EnrichmentFormatError):
            parse_tags({"tags": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
