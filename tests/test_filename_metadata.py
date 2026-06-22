import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.filename_metadata import match_publisher_alias


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


if __name__ == "__main__":
    unittest.main()
