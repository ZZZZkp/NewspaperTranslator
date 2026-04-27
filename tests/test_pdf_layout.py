import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

SAMPLE_ROOT = PROJECT_ROOT.parent
WSJ_SAMPLE = SAMPLE_ROOT / "华尔街日报-4-20.pdf"
GUARDIAN_SAMPLE = SAMPLE_ROOT / "卫报-4-21.pdf"

try:
    from newspaper_translator.pdf import (
        build_positioned_text_blocks,
        extract_articles_from_mineru_markdown,
        parse_pdf_articles,
        extract_page_articles,
        extract_article_candidate_blocks,
        extract_positioned_text_fragments,
    )
except ImportError:
    build_positioned_text_blocks = None
    extract_articles_from_mineru_markdown = None
    parse_pdf_articles = None
    extract_page_articles = None
    extract_article_candidate_blocks = None
    extract_positioned_text_fragments = None


class PdfLayoutTests(unittest.TestCase):
    def test_extracts_positioned_text_fragments_from_digital_sample_page(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertIsNotNone(
            extract_positioned_text_fragments,
            "extract_positioned_text_fragments should be importable from newspaper_translator.pdf",
        )

        fragments = extract_positioned_text_fragments(WSJ_SAMPLE, page_number=1)

        self.assertGreater(len(fragments), 100)
        self.assertEqual(fragments[0].page_number, 1)

        matching_fragments = [fragment for fragment in fragments if fragment.text == "talks to acquire Kelonia"]
        self.assertEqual(len(matching_fragments), 1)

        title_fragment = matching_fragments[0]
        self.assertGreater(title_fragment.x, 90.0)
        self.assertLess(title_fragment.x, 120.0)
        self.assertGreater(title_fragment.y, 980.0)
        self.assertLess(title_fragment.y, 1010.0)

    def test_groups_positioned_fragments_into_a_two_line_headline_block(self) -> None:
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertIsNotNone(
            build_positioned_text_blocks,
            "build_positioned_text_blocks should be importable from newspaper_translator.pdf",
        )

        blocks = build_positioned_text_blocks(GUARDIAN_SAMPLE, page_number=1)

        matching_blocks = [block for block in blocks if "Margarita time?Gin gives way to" in block.text]
        self.assertEqual(len(matching_blocks), 1)

        headline_block = matching_blocks[0]
        self.assertEqual(headline_block.line_count, 2)
        self.assertIn("tequila as top summer tipple", headline_block.text)
        self.assertGreater(headline_block.x, 320.0)
        self.assertLess(headline_block.x, 360.0)
        self.assertGreater(headline_block.y_top, 930.0)
        self.assertLess(headline_block.y_top, 970.0)

    def test_extracts_article_candidate_blocks_without_section_noise(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertIsNotNone(
            extract_article_candidate_blocks,
            "extract_article_candidate_blocks should be importable from newspaper_translator.pdf",
        )

        candidates = extract_article_candidate_blocks(WSJ_SAMPLE, page_number=1)

        matching_candidates = [
            candidate for candidate in candidates if candidate.title == "talks to acquire Kelonia"
        ]
        self.assertEqual(len(matching_candidates), 1)

        kelonia_candidate = matching_candidates[0]
        self.assertIn("Therapeutics for more than", kelonia_candidate.body_text)
        self.assertNotIn("What’s", kelonia_candidate.body_text)
        self.assertNotIn("Business & Finance", kelonia_candidate.body_text)

    def test_extracts_same_page_article_by_merging_continuation_blocks(self) -> None:
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertIsNotNone(
            extract_page_articles,
            "extract_page_articles should be importable from newspaper_translator.pdf",
        )

        articles = extract_page_articles(WSJ_SAMPLE, page_number=1)

        matching_articles = [article for article in articles if article.title == "talks to acquire Kelonia"]
        self.assertEqual(len(matching_articles), 1)

        kelonia_article = matching_articles[0]
        self.assertIn("Therapeutics for more than", kelonia_article.body_text)
        self.assertIn("sideration if Kelonia reaches", kelonia_article.body_text)
        self.assertIn("certain milestones.", kelonia_article.body_text)
        self.assertNotIn("TheTrumpOrganization", kelonia_article.body_text)
        self.assertEqual(kelonia_article.page_number, 1)

    def test_does_not_treat_bylines_as_article_titles(self) -> None:
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertIsNotNone(
            extract_page_articles,
            "extract_page_articles should be importable from newspaper_translator.pdf",
        )

        articles = extract_page_articles(GUARDIAN_SAMPLE, page_number=1)
        article_titles = {article.title for article in articles}

        self.assertIn("Sacked oﬃ  cial to set out", article_titles)
        self.assertNotIn("Pippa Crerar", article_titles)
        self.assertNotIn("Dan Sabbagh", article_titles)

    def test_merges_byline_and_body_blocks_into_same_page_article(self) -> None:
        self.assertTrue(GUARDIAN_SAMPLE.exists(), f"Missing sample PDF: {GUARDIAN_SAMPLE}")
        self.assertIsNotNone(
            extract_page_articles,
            "extract_page_articles should be importable from newspaper_translator.pdf",
        )

        articles = extract_page_articles(GUARDIAN_SAMPLE, page_number=1)

        matching_articles = [article for article in articles if article.title == "Sacked oﬃ  cial to set out"]
        self.assertEqual(len(matching_articles), 1)

        guardian_article = matching_articles[0]
        self.assertIn("Pippa Crerar", guardian_article.body_text)
        self.assertIn("Jessica Elgot", guardian_article.body_text)
        self.assertIn("Keir Starmer has accused Olly Rob-", guardian_article.body_text)
        self.assertNotIn("Vance to lead US envoys", guardian_article.body_text)

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
        self.assertTrue(WSJ_SAMPLE.exists(), f"Missing sample PDF: {WSJ_SAMPLE}")
        self.assertIsNotNone(
            parse_pdf_articles,
            "parse_pdf_articles should be importable from newspaper_translator.pdf",
        )

        fake_client = _FakeMineruClient(
            markdown_text="# talks to acquire Kelonia\n\nTherapeutics for more than $2 billion.\n"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            articles = parse_pdf_articles(
                WSJ_SAMPLE,
                output_root=pathlib.Path(temp_dir),
                mineru_client=fake_client,
            )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "talks to acquire Kelonia")
        self.assertIn("Therapeutics for more than", articles[0].body_text)
        self.assertEqual(fake_client.calls[0]["pdf_path"], WSJ_SAMPLE)


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


if __name__ == "__main__":
    unittest.main()
