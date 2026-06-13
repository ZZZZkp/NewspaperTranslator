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


if __name__ == "__main__":
    unittest.main()
