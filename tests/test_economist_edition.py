import pathlib
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.economist_edition import (
        ArticleRange,
        OutlineEntry,
        compute_article_ranges,
    )
except ImportError:
    ArticleRange = None
    OutlineEntry = None
    compute_article_ranges = None

try:
    from newspaper_translator.economist_edition import clean_edition_text
except ImportError:
    clean_edition_text = None

try:
    from newspaper_translator.economist_edition import (
        EditionArticle,
        build_economist_parse_result,
    )
except ImportError:
    EditionArticle = None
    build_economist_parse_result = None


class ComputeArticleRangesTests(unittest.TestCase):
    def test_leaf_end_is_next_boundary_including_section_landing_pages(self) -> None:
        self.assertIsNotNone(compute_article_ranges)
        entries = [
            OutlineEntry(title="Leaders", section="", start_page=16, is_leaf=False),
            OutlineEntry(title="The World Cup paradox", section="Leaders", start_page=17, is_leaf=True),
            OutlineEntry(title="Behind the wheel", section="Leaders", start_page=36, is_leaf=True),
            OutlineEntry(title="Letters", section="", start_page=40, is_leaf=False),
            OutlineEntry(title="Premier League", section="Letters", start_page=41, is_leaf=True),
        ]

        ranges = compute_article_ranges(entries, total_pages=47)

        self.assertEqual(
            ranges,
            [
                ArticleRange(title="The World Cup paradox", section="Leaders", start_page=17, end_page=36),
                # ends at the Letters landing page (40), NOT swallowing it
                ArticleRange(title="Behind the wheel", section="Leaders", start_page=36, end_page=40),
                # last leaf ends at total_pages + 1
                ArticleRange(title="Premier League", section="Letters", start_page=41, end_page=48),
            ],
        )


class CleanEditionTextTests(unittest.TestCase):
    def test_strips_nav_timestamp_marker_and_extracts_wrapped_url(self) -> None:
        self.assertIsNotNone(clean_edition_text)
        raw = "\n".join(
            [
                "| 下一项 | 章节菜单 | 主菜单 | 上一项 |",
                "Dire strait",
                "Donald Trump's least bad option in Iran",
                "He must swallow his pride.",
                "6 ⽉ 11, 2026 04:21 上午",
                "ONCE AGAIN, Iran has been defeated.",
                "kicked off.■",
                "",
                "Subscribers to The Economist can sign up to our Opinion newsletter.",
                "This article was downloaded by calibre from",
                "https://www.economist.com/leaders/2026/06/10/the-world-",
                "cup-paradox",
                "| 章节菜单 | 主菜单 |",
            ]
        )

        body, url = clean_edition_text(raw)

        self.assertIn("Donald Trump's least bad option in Iran", body)
        self.assertIn("ONCE AGAIN, Iran has been defeated.", body)
        self.assertIn("kicked off.", body)
        self.assertNotIn("■", body)
        self.assertNotIn("章节菜单", body)
        self.assertNotIn("主菜单", body)
        self.assertNotIn("上午", body)  # timestamp line removed
        self.assertNotIn("Subscribers to The Economist", body)  # promo truncated
        self.assertNotIn("downloaded by calibre", body)
        self.assertEqual(
            url,
            "https://www.economist.com/leaders/2026/06/10/the-world-cup-paradox",
        )

    def test_returns_empty_url_when_marker_absent(self) -> None:
        body, url = clean_edition_text("Plain body with no calibre footer.")
        self.assertEqual(url, "")
        self.assertEqual(body, "Plain body with no calibre footer.")

    def test_strips_nav_bar_with_kangxi_radical_one_variant(self) -> None:
        # Real Economist PDFs render 下⼀项/上⼀项 with the Kangxi radical one
        # (U+2F00), not the normal 一 (U+4E00). The cleaner must still drop them.
        nav = "| 下⼀项 | 章节菜单 | 主菜单 | 上⼀项 |"
        raw = "\n".join([nav, "Real body sentence here.", nav])
        body, _url = clean_edition_text(raw)
        self.assertNotIn("⼀", body)
        self.assertNotIn("章节菜单", body)  # 章节菜单
        self.assertEqual(body, "Real body sentence here.")


class BuildParseResultTests(unittest.TestCase):
    def test_each_article_becomes_one_standalone_parsed_article(self) -> None:
        self.assertIsNotNone(build_economist_parse_result)
        articles = [
            EditionArticle(
                title="The World Cup paradox",
                section="Leaders",
                start_page=17,
                end_page=23,
                body_text="Body one.",
                url="https://www.economist.com/leaders/2026/06/10/the-world-cup-paradox",
            ),
            EditionArticle(
                title="Least bad option in Iran",
                section="Leaders",
                start_page=23,
                end_page=27,
                body_text="Body two.",
                url="https://www.economist.com/leaders/2026/06/10/iran",
            ),
        ]

        parse_result = build_economist_parse_result(articles)

        self.assertEqual(parse_result.match_decisions, [])
        self.assertEqual(len(parse_result.fragments), 2)
        self.assertEqual(len(parse_result.articles), 2)

        first_fragment = parse_result.fragments[0]
        self.assertEqual(first_fragment.source_order, 1)
        self.assertEqual(first_fragment.page_number, 17)
        self.assertEqual(first_fragment.title, "The World Cup paradox")
        self.assertEqual(first_fragment.continued_to_page, "")
        self.assertEqual(first_fragment.continued_from_page, "")

        second_article = parse_result.articles[1]
        self.assertEqual(second_article.article_order, 2)
        self.assertEqual(second_article.primary_source_order, 2)
        self.assertEqual(second_article.source_fragment_count, 1)
        self.assertEqual(second_article.title, "Least bad option in Iran")
        self.assertEqual(second_article.body_text, "Body two.")
        self.assertEqual(len(second_article.source_fragments), 1)
        self.assertEqual(second_article.source_fragments[0].fragment_role, "standalone")
        self.assertEqual(second_article.source_fragments[0].sequence_index, 1)


try:
    from newspaper_translator.economist_edition import (
        ParsedEdition,
        detect_calibre_economist_edition,
        extract_article_text,
        extract_outline_entries,
        parse_economist_edition,
    )
except ImportError:
    ParsedEdition = None
    detect_calibre_economist_edition = None
    extract_article_text = None
    extract_outline_entries = None
    parse_economist_edition = None


class _FakeDest:
    def __init__(self, title: str, page0: int) -> None:
        self.title = title
        self.page0 = page0


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    def __init__(self, *, outline, pages, metadata) -> None:
        self.outline = outline
        self.pages = pages
        self.metadata = metadata

    def get_destination_page_number(self, dest) -> int:
        return dest.page0  # 0-based


def _economist_reader() -> "_FakeReader":
    # outline: "Leaders" (section) -> [paradox leaf, iran leaf]; "Letters" (section) -> [premier leaf]
    leaders = _FakeDest("Leaders", 1)
    paradox = _FakeDest("The World Cup paradox", 2)
    iran = _FakeDest("Least bad option in Iran", 3)
    letters = _FakeDest("Letters", 4)
    premier = _FakeDest("Premier League", 5)
    outline = [leaders, [paradox, iran], letters, [premier]]
    pages = [
        _FakePage("cover"),                                   # page 1
        _FakePage("Leaders landing"),                          # page 2
        _FakePage("Body paradox. downloaded by calibre from\nhttps://www.economist.com/leaders/2026/06/10/paradox"),  # page 3
        _FakePage("Body iran."),                               # page 4
        _FakePage("Letters landing"),                          # page 5
        _FakePage("Body premier."),                            # page 6
    ]
    metadata = {"/Producer": "calibre 9.1.0", "/Title": "The Economist [June 13th 2026]"}
    return _FakeReader(outline=outline, pages=pages, metadata=metadata)


class OutlineAndDetectionTests(unittest.TestCase):
    def test_extract_outline_entries_marks_leaves_and_sections(self) -> None:
        self.assertIsNotNone(extract_outline_entries)
        entries = extract_outline_entries(_economist_reader())

        leaves = [(entry.title, entry.section, entry.start_page) for entry in entries if entry.is_leaf]
        self.assertEqual(
            leaves,
            [
                ("The World Cup paradox", "Leaders", 3),
                ("Least bad option in Iran", "Leaders", 4),
                ("Premier League", "Letters", 6),
            ],
        )
        sections = [entry.title for entry in entries if not entry.is_leaf]
        self.assertEqual(sections, ["Leaders", "Letters"])

    def test_detect_true_for_calibre_economist_edition(self) -> None:
        reader = _economist_reader()
        with patch("newspaper_translator.economist_edition.PdfReader", return_value=reader):
            self.assertTrue(detect_calibre_economist_edition("any.pdf"))

    def test_detect_true_via_economist_dot_com_text_when_title_neutral(self) -> None:
        reader = _economist_reader()
        reader.metadata = {"/Producer": "calibre 9.1.0", "/Title": "Calibre Library"}
        with patch("newspaper_translator.economist_edition.PdfReader", return_value=reader):
            self.assertTrue(detect_calibre_economist_edition("any.pdf"))

    def test_detect_false_for_non_calibre_pdf(self) -> None:
        reader = _economist_reader()
        reader.metadata = {"/Producer": "Adobe", "/Title": "The Economist"}
        with patch("newspaper_translator.economist_edition.PdfReader", return_value=reader):
            self.assertFalse(detect_calibre_economist_edition("any.pdf"))

    def test_detect_false_on_read_error(self) -> None:
        with patch(
            "newspaper_translator.economist_edition.PdfReader",
            side_effect=ValueError("broken pdf"),
        ):
            self.assertFalse(detect_calibre_economist_edition("any.pdf"))

    def test_parse_economist_edition_produces_articles_with_clean_body(self) -> None:
        reader = _economist_reader()
        with patch("newspaper_translator.economist_edition.PdfReader", return_value=reader):
            edition = parse_economist_edition("any.pdf")

        titles = [article.title for article in edition.parse_result.articles]
        self.assertEqual(
            titles,
            ["The World Cup paradox", "Least bad option in Iran", "Premier League"],
        )
        first_body = edition.parse_result.articles[0].body_text
        self.assertIn("Body paradox.", first_body)
        self.assertNotIn("downloaded by calibre", first_body)
        self.assertIn("economist.com/leaders/2026/06/10/paradox", edition.debug_text)


if __name__ == "__main__":
    unittest.main()
