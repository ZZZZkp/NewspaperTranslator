import pathlib
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
