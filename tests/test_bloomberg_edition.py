import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.bloomberg_edition import ContentsEntry, parse_contents_entries

# Real Contents-page lines from the sample issue (physical page 10).
SAMPLE_CONTENTS = "\n".join([
    " Bloomberg Businessweek8",
    "Contents Contributors",
    "Cover",
    "Remarks How will AI alter the economy? Ask a scarecrow 10",
    "In Context It’s a cruel summer for business owners everywhere 15",
    " Will the World Cup bring more drama on the ﬁeld or off? 19",
    " Seeking a better way to farm salmon 20",
    "In View Newer supporters to Trump: “We didn’t vote for this” 37",
    " Disposable labor powers the US workforce 40",
    "The AI Issue Constructing the global AI brain 43",
    " Andy Jassy on Amazon’s massive AI ambitions 44",
    "United’s CEO is fighting turf wars—and ",
    "courting\xa0influencers 84",
    "Pursuits It’s time to take back your time 93",
    "Exit Strategy What’s Chuck E. Cheese running from? 108",
    "How to contact Bloomberg Businessweek ⊿ Email bwreader@bloomberg.net ⊿ Ad sales 212 617-2900",
])


class ParseContentsEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = parse_contents_entries(SAMPLE_CONTENTS, max_folio=112)

    def test_folios_are_monotonic_and_in_range(self) -> None:
        folios = [e.folio for e in self.entries]
        self.assertEqual(folios, sorted(folios))
        self.assertTrue(all(1 <= f <= 112 for f in folios))

    def test_first_and_last_entries(self) -> None:
        self.assertEqual(self.entries[0].folio, 10)
        self.assertIn("How will AI alter the economy", self.entries[0].title)
        self.assertEqual(self.entries[-1].folio, 108)
        self.assertIn("Chuck E. Cheese", self.entries[-1].title)

    def test_wrapped_title_is_joined(self) -> None:
        wrapped = [e for e in self.entries if e.folio == 84]
        self.assertEqual(len(wrapped), 1)
        self.assertIn("United", wrapped[0].title)
        self.assertIn("courting", wrapped[0].title)

    def test_footer_phone_line_is_excluded(self) -> None:
        self.assertTrue(all("Ad sales" not in e.title for e in self.entries))
        self.assertTrue(all(e.folio != 212 for e in self.entries))

    def test_known_section_labels_are_split_off(self) -> None:
        remarks = [e for e in self.entries if e.folio == 10][0]
        self.assertEqual(remarks.section, "Remarks")
        self.assertNotIn("Remarks", remarks.title)
        # Carried forward to sub-entries until the next known label.
        farm = [e for e in self.entries if e.folio == 20][0]
        self.assertEqual(farm.section, "In Context")


from newspaper_translator.bloomberg_edition import find_contents_page, detect_page_offset


class _StubPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _StubReader:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [_StubPage(t) for t in texts]


class FindContentsPageTests(unittest.TestCase):
    def test_finds_contents_page_index(self) -> None:
        # The Contents page must yield >= 8 entries to be accepted.
        listing = "\n".join(f"Item {i} title here {10 + i}" for i in range(8))
        reader = _StubReader([
            "cover art only",
            "masthead",
            "Contents Contributors\n" + listing,
        ])
        self.assertEqual(find_contents_page(reader), 2)

    def test_returns_none_when_no_contents(self) -> None:
        reader = _StubReader(["just a cover", "an article with prose and no listing"])
        self.assertIsNone(find_contents_page(reader))


class DetectPageOffsetTests(unittest.TestCase):
    def test_detects_constant_offset_by_vote(self) -> None:
        # physical index 7 (1-based 8) prints folio 6 -> offset +2, etc.
        texts = [""] * 24
        texts[7] = "Bloomberg Businessweek6\nbody"
        texts[9] = "Bloomberg Businessweek8\nbody"
        texts[11] = "Bloomberg Businessweek10\nbody"
        texts[21] = "Bloomberg Businessweek20\nbody"
        texts[3] = "noise"
        reader = _StubReader(texts)
        self.assertEqual(detect_page_offset(reader), 2)

    def test_returns_none_without_enough_markers(self) -> None:
        reader = _StubReader(["no folio here", "still none"])
        self.assertIsNone(detect_page_offset(reader))


from newspaper_translator.bloomberg_edition import (
    BloombergArticleRange,
    compute_article_ranges,
)


class ComputeArticleRangesTests(unittest.TestCase):
    def test_ranges_use_offset_and_span_to_next(self) -> None:
        entries = [
            ContentsEntry("A", "Remarks", 10),
            ContentsEntry("B", "In Context", 15),
            ContentsEntry("C", "Exit", 108),
        ]
        ranges = compute_article_ranges(entries, offset=2, total_pages=112)
        self.assertEqual(
            [(r.start_page, r.end_page) for r in ranges],
            [(12, 17), (17, 110), (110, 113)],
        )
        self.assertEqual(ranges[0].title, "A")

    def test_pages_before_first_entry_are_dropped(self) -> None:
        ranges = compute_article_ranges(
            [ContentsEntry("A", "", 10)], offset=2, total_pages=20
        )
        self.assertEqual(ranges[0].start_page, 12)  # pages 1..11 not covered
