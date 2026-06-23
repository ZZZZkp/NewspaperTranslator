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
