import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.article_pipeline import resolve_publication_date


class ResolvePublicationDateTests(unittest.TestCase):
    def test_issue_date_is_authoritative(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="The Economist USA - June 20 2026.pdf",
                markdown_text="May 1, 2020",
                issue_date="2026-06-20",
            ),
            "2026-06-20",
        )

    def test_falls_back_when_issue_date_missing(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="wsj-2026-05-06.pdf",
                markdown_text="",
                issue_date=None,
            ),
            "2026-05-06",
        )


if __name__ == "__main__":
    unittest.main()
