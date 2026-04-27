import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.pdf import (
        extract_article_fragments_from_mineru_markdown,
        extract_articles_from_mineru_markdown,
        parse_pdf_articles,
    )
except ImportError:
    extract_article_fragments_from_mineru_markdown = None
    extract_articles_from_mineru_markdown = None
    parse_pdf_articles = None


class PdfLayoutTests(unittest.TestCase):
    def test_extracts_continued_to_page_from_mineru_markdown(self) -> None:
        self.assertIsNotNone(
            extract_article_fragments_from_mineru_markdown,
            "extract_article_fragments_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "Exxon, Chevron and others turn to Africa and South America for next prospects\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "Please turn to page A7\n"
        )

        fragments = extract_article_fragments_from_mineru_markdown(markdown_text)

        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0].title, "Big Oil Explores Farther Afield To Dodge Middle East Turmoil")
        self.assertEqual(fragments[0].continued_to_page, "A7")
        self.assertEqual(fragments[0].continued_from_page, "")

    def test_extracts_articles_from_mineru_markdown(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Sacked official to set out\n\n"
            "his side of story after PM's Commons claims\n\n"
            "Pippa Crerar\n"
            "Jessica Elgot\n\n"
            "Keir Starmer has accused Olly Robbins of deliberately obstructing the truth.\n\n"
            "# Vance to lead US envoys\n\n"
            "if Tehran agrees to talks\n"
        )

        articles = extract_articles_from_mineru_markdown(markdown_text)

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].title, "Sacked official to set out")
        self.assertIn("Pippa Crerar", articles[0].body_text)
        self.assertIn("Keir Starmer has accused Olly Robbins", articles[0].body_text)
        self.assertEqual(articles[1].title, "Vance to lead US envoys")

    def test_extracts_continued_from_page_from_mineru_markdown(self) -> None:
        self.assertIsNotNone(
            extract_article_fragments_from_mineru_markdown,
            "extract_article_fragments_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        fragments = extract_article_fragments_from_mineru_markdown(markdown_text)

        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0].continued_to_page, "")
        self.assertEqual(fragments[0].continued_from_page, "PageOne")

    def test_merges_mineru_subtitle_and_byline_heading_into_same_article(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "Exxon, Chevron and others turn to Africa and South America for next prospects\n\n"
            "# BY COLLIN EATON\n\n"
            "Exxon Mobil, Chevron and other energy companies are speeding up their searches for new oil-and-gas prospects.\n\n"
            "Iran's attacks on energy infrastructure have sparked a global scramble for oil.\n\n"
            "# Trump Grapples With Fears on War\n\n"
            "President's impulsive style hasn't been tested during a sustained military conflict\n"
        )

        articles = extract_articles_from_mineru_markdown(markdown_text)

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].title, "Big Oil Explores Farther Afield To Dodge Middle East Turmoil")
        self.assertIn(
            "Exxon, Chevron and others turn to Africa and South America for next prospects",
            articles[0].body_text,
        )
        self.assertIn("BY COLLIN EATON", articles[0].body_text)
        self.assertIn("Exxon Mobil, Chevron and other energy companies", articles[0].body_text)
        self.assertNotEqual(articles[1].title, "BY COLLIN EATON")
        self.assertEqual(articles[1].title, "Trump Grapples With Fears on War")

    def test_merges_matched_cross_page_fragments(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "Exxon, Chevron and others turn to Africa and South America for next prospects\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "Please turn to page A7\n\n"
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        matcher = _FakeContinuationMatcher(matches=[(1, 2)])

        articles = extract_articles_from_mineru_markdown(markdown_text, continuation_matcher=matcher)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Big Oil Explores Farther Afield To Dodge Middle East Turmoil")
        self.assertIn("U.S. oil futures were trading near $90 a barrel Sunday.", articles[0].body_text)
        self.assertIn("The oil companies want to maximize their production.", articles[0].body_text)

    def test_removes_continuation_markers_after_merge(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "PleaseturntopageA7\n\n"
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        matcher = _FakeContinuationMatcher(matches=[(1, 2)])

        articles = extract_articles_from_mineru_markdown(markdown_text, continuation_matcher=matcher)

        self.assertEqual(len(articles), 1)
        self.assertNotIn("PleaseturntopageA7", articles[0].body_text)
        self.assertNotIn("Continued from PageOne", articles[0].body_text)

    def test_passes_only_continuation_fragments_to_matcher(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "Please turn to page A7\n\n"
            "# New York Parade Honors Tehran Regime’s Victims\n\n"
            "Supporters carried the traditional flag of Iran as they marched along Madison Avenue.\n\n"
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        matcher = _FakeContinuationMatcher(matches=[(1, 3)])

        extract_articles_from_mineru_markdown(markdown_text, continuation_matcher=matcher)

        self.assertEqual(len(matcher.calls), 1)
        self.assertEqual(len(matcher.calls[0]), 2)
        self.assertEqual([fragment.title for fragment in matcher.calls[0]], [
            "Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
            "Big Oil Explores Farther Out",
        ])

    def test_keeps_unmerged_fragments_when_continuation_matcher_fails(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "Please turn to page A7\n\n"
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        articles = extract_articles_from_mineru_markdown(
            markdown_text,
            continuation_matcher=_FailingContinuationMatcher(),
        )

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].title, "Big Oil Explores Farther Afield To Dodge Middle East Turmoil")
        self.assertEqual(articles[1].title, "Big Oil Explores Farther Out")

    def test_ignores_mineru_teaser_blocks_with_leader_dots(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# In War's Grip\n\n"
            "Pentagon clash at top spills\n"
            "into the open........................ A1\n"
            "U.S. prepares for uranium\n"
            "removal in Iran .................... A6\n"
            "U.A.E. asks U.S. officials\n\n"
            "# Divides On Strait, Uranium Imperil Iran Talks\n\n"
            "Tehran threatens to skip session; U.S. seizes a vessel trying to slip past blockade\n\n"
            "Vice President JD Vance is expected to lead a new round of peace talks with Iran in Pakistan.\n"
        )

        articles = extract_articles_from_mineru_markdown(markdown_text)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Divides On Strait, Uranium Imperil Iran Talks")
        self.assertNotIn("into the open........................ A1", articles[0].body_text)

    def test_ignores_mineru_digest_blocks_with_section_promos(self) -> None:
        self.assertIsNotNone(
            extract_articles_from_mineru_markdown,
            "extract_articles_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# In War's Grip\n\n"
            "Pentagon clash at top spills\n"
            "into the open........................ A1\n"
            "U.S. prepares for uranium\n"
            "removal in Iran .................... A6\n"
            "U.A.E. asks U.S. officials\n"
            "![](images/inside.jpg)\n"
            "SPORTS\n"
            "A fight breaks out over train prices for World Cup matches in New Jersey. A16\n"
            "![](images/business.jpg)\n"
            "BUSINESS & FINANCE\n"
            "Blue Origin's first commercial launch for its new rocket suffers a mission hiccup. B3\n\n"
            "# Does This Shirt Make Me Look Like a Nerd? Mission Accomplished.\n\n"
            "The hottest gear in Silicon Valley features the faces of tech CEOs; $178 Nvidia sweater\n\n"
            "# BY ROBBIE WHELAN\n\n"
            "SAN JOSE-Hardik Nahata was browsing merchandise at Nvidia's annual conference.\n"
        )

        articles = extract_articles_from_mineru_markdown(markdown_text)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Does This Shirt Make Me Look Like a Nerd? Mission Accomplished.")
        self.assertNotIn("Blue Origin's first commercial launch", articles[0].body_text)

    def test_phase_3_entry_uses_mineru_client_output(self) -> None:
        self.assertIsNotNone(
            parse_pdf_articles,
            "parse_pdf_articles should be importable from newspaper_translator.pdf",
        )

        fake_client = _FakeMineruClient(
            markdown_text="# talks to acquire Kelonia\n\nTherapeutics for more than $2 billion.\n"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            articles = parse_pdf_articles(
                pdf_path,
                output_root=pathlib.Path(temp_dir),
                mineru_client=fake_client,
            )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "talks to acquire Kelonia")
        self.assertIn("Therapeutics for more than", articles[0].body_text)
        self.assertEqual(fake_client.calls[0]["pdf_path"], pdf_path)

    def test_phase_3_entry_accepts_continuation_matcher(self) -> None:
        self.assertIsNotNone(
            parse_pdf_articles,
            "parse_pdf_articles should be importable from newspaper_translator.pdf",
        )

        fake_client = _FakeMineruClient(
            markdown_text=(
                "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
                "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
                "Please turn to page A7\n\n"
                "# Big Oil Explores Farther Out\n\n"
                "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
                "The oil companies want to maximize their production.\n"
            )
        )
        matcher = _FakeContinuationMatcher(matches=[(1, 2)])

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            articles = parse_pdf_articles(
                pdf_path,
                output_root=pathlib.Path(temp_dir),
                mineru_client=fake_client,
                continuation_matcher=matcher,
            )

        self.assertEqual(len(articles), 1)
        self.assertIn("The oil companies want to maximize their production.", articles[0].body_text)


class _FakeMineruClient:
    def __init__(self, *, markdown_text: str) -> None:
        self._markdown_text = markdown_text
        self.calls: list[dict[str, object]] = []

    def parse_pdf(self, *, pdf_path: pathlib.Path, output_root: pathlib.Path):
        self.calls.append({"pdf_path": pdf_path, "output_root": output_root})
        return type(
            "FakeMineruParsedDocument",
            (),
            {
                "markdown_text": self._markdown_text,
            },
        )()


class _FakeContinuationMatcher:
    def __init__(self, *, matches: list[tuple[int, int]]) -> None:
        self._matches = matches
        self.calls: list[list[object]] = []

    def __call__(self, fragments):
        self.calls.append(list(fragments))
        return list(self._matches)


class _FailingContinuationMatcher:
    def __call__(self, fragments):
        raise RuntimeError("matcher unavailable")


if __name__ == "__main__":
    unittest.main()
