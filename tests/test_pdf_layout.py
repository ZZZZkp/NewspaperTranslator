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
        build_parse_result_from_mineru_markdown,
        extract_article_fragments_from_mineru_markdown,
        extract_articles_from_mineru_markdown,
        parse_pdf_articles,
    )
except ImportError:
    build_parse_result_from_mineru_markdown = None
    extract_article_fragments_from_mineru_markdown = None
    extract_articles_from_mineru_markdown = None
    parse_pdf_articles = None


class PdfLayoutTests(unittest.TestCase):
    def test_builds_parse_result_with_match_lineage_for_persistence(self) -> None:
        self.assertIsNotNone(
            build_parse_result_from_mineru_markdown,
            "build_parse_result_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "Please turn to page A7\n\n"
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        parse_result = build_parse_result_from_mineru_markdown(
            markdown_text,
            continuation_matcher=_FakeContinuationMatcher(matches=[(1, 2)]),
        )

        self.assertEqual(len(parse_result.fragments), 2)
        self.assertEqual(len(parse_result.match_decisions), 1)
        self.assertEqual(parse_result.match_decisions[0].decision_status, "accepted")
        self.assertEqual(parse_result.match_decisions[0].front_source_order, 1)
        self.assertEqual(parse_result.match_decisions[0].back_source_order, 2)
        self.assertEqual(len(parse_result.articles), 1)
        self.assertEqual(parse_result.articles[0].article_order, 1)
        self.assertEqual(parse_result.articles[0].primary_source_order, 1)
        self.assertEqual(parse_result.articles[0].source_fragment_count, 2)
        self.assertEqual(
            [
                (source.source_order, source.fragment_role, source.sequence_index)
                for source in parse_result.articles[0].source_fragments
            ],
            [
                (1, "front", 1),
                (2, "back", 2),
            ],
        )
        self.assertNotIn("Please turn to page A7", parse_result.articles[0].body_text)
        self.assertNotIn("Continued from PageOne", parse_result.articles[0].body_text)

    def test_records_invalid_match_decisions_without_losing_fragments(self) -> None:
        self.assertIsNotNone(
            build_parse_result_from_mineru_markdown,
            "build_parse_result_from_mineru_markdown should be importable from newspaper_translator.pdf",
        )

        markdown_text = (
            "# Big Oil Explores Farther Afield To Dodge Middle East Turmoil\n\n"
            "U.S. oil futures were trading near $90 a barrel Sunday.\n\n"
            "Please turn to page A7\n\n"
            "# Big Oil Explores Farther Out\n\n"
            "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n\n"
            "The oil companies want to maximize their production.\n"
        )

        parse_result = build_parse_result_from_mineru_markdown(
            markdown_text,
            continuation_matcher=_FakeContinuationMatcher(matches=[(1, 99)]),
        )

        self.assertEqual(len(parse_result.fragments), 2)
        self.assertEqual(len(parse_result.match_decisions), 1)
        self.assertEqual(parse_result.match_decisions[0].decision_status, "invalid")
        self.assertIn("unknown fragment", parse_result.match_decisions[0].decision_reason)
        self.assertEqual(len(parse_result.articles), 2)
        self.assertEqual(
            [
                (article.primary_source_order, article.source_fragment_count)
                for article in parse_result.articles
            ],
            [
                (1, 1),
                (2, 1),
            ],
        )

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

    def test_solid_triangle_sets_continued_to_page(self) -> None:
        from newspaper_translator.pdf import _extract_continued_to_page
        self.assertEqual(_extract_continued_to_page("the story continues ►84"), "84")

    def test_solid_triangle_sets_continued_from_page(self) -> None:
        from newspaper_translator.pdf import _extract_continued_from_page
        self.assertEqual(_extract_continued_from_page("◄52 the story resumes"), "52")

    def test_white_triangle_cross_reference_is_ignored(self) -> None:
        from newspaper_translator.pdf import _extract_continued_to_page
        self.assertEqual(_extract_continued_to_page("see related coverage ▷54"), "")

    def test_merge_strips_solid_triangle_markers(self) -> None:
        from newspaper_translator.pdf import ArticleFragment, _merge_fragment_body_text
        front = ArticleFragment(title="t", body_text="front body ►84", source_order=1,
                                continued_to_page="84", continued_from_page="", page_number=1)
        back = ArticleFragment(title="t", body_text="◄52 back body", source_order=2,
                               continued_to_page="", continued_from_page="52", page_number=3)
        self.assertEqual(_merge_fragment_body_text(front, back), "front body\nback body")

    def test_inline_triangle_bullet_is_not_a_continuation(self) -> None:
        from newspaper_translator.pdf import _extract_continued_to_page, _extract_continued_from_page
        # An inline solid-triangle bullet mid-text must not be read as a jump page.
        self.assertEqual(_extract_continued_to_page("►3 key points about the economy"), "")
        # The real continuation note sits at the fragment boundary.
        self.assertEqual(_extract_continued_to_page("the story continues ►84"), "84")
        self.assertEqual(_extract_continued_from_page("◄52 the story resumes here"), "52")

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

    def test_phase_3_entry_uses_page_sliced_mineru_client_when_available(self) -> None:
        from newspaper_translator.mineru import MineruParsedDocument, MineruParsedPage
        from newspaper_translator.pdf import parse_pdf_articles

        fake_client = _FakePageSlicedMineruClient(
            parsed_document=MineruParsedDocument(
                batch_id="batch-1",
                file_id="sample",
                file_name="sample.pdf",
                markdown_path=pathlib.Path("/tmp/full-pages.md"),
                markdown_text="merged",
                pages=(
                    MineruParsedPage(
                        page_number=5,
                        batch_id="batch-1",
                        file_id="page-0005",
                        file_name="page-0005.pdf",
                        markdown_path=pathlib.Path("/tmp/page-0005.md"),
                        markdown_text="# Headline\n\nBody\n",
                    ),
                ),
            )
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
        self.assertEqual(articles[0].page_number, 5)
        self.assertEqual(fake_client.calls[0]["method"], "parse_pdf_by_pages")

    def test_build_parse_result_from_mineru_pages_preserves_physical_page_numbers(self) -> None:
        from newspaper_translator.pdf import (
            ParsedMarkdownPage,
            build_parse_result_from_mineru_pages,
        )

        matcher = _FakeContinuationMatcher(matches=[(1, 2)])

        parse_result = build_parse_result_from_mineru_pages(
            [
                ParsedMarkdownPage(
                    page_number=1,
                    markdown_text=(
                        "# Big Oil Explores Farther Afield\n\n"
                        "U.S. oil futures were trading near $90 a barrel.\n"
                        "Please turn to page A7\n"
                    ),
                ),
                ParsedMarkdownPage(
                    page_number=7,
                    markdown_text=(
                        "# Big Oil Explores Farther Out\n\n"
                        "Continued from PageOne after the Strait of Hormuz reopened.\n"
                    ),
                ),
            ],
            continuation_matcher=matcher,
        )

        self.assertEqual([fragment.page_number for fragment in parse_result.fragments], [1, 7])
        self.assertEqual([fragment.source_order for fragment in parse_result.fragments], [1, 2])
        self.assertEqual(len(parse_result.articles), 1)
        article = parse_result.articles[0]
        source_pages = [
            parse_result.fragments[source.source_order - 1].page_number
            for source in article.source_fragments
        ]
        self.assertEqual(source_pages, [1, 7])

    def test_split_pdf_into_single_page_files_writes_1_based_page_artifacts(self) -> None:
        from pypdf import PdfReader, PdfWriter
        from newspaper_translator.pdf import split_pdf_into_single_page_files

        with tempfile.TemporaryDirectory() as temp_dir:
            source_pdf = pathlib.Path(temp_dir) / "sample.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.add_blank_page(width=72, height=72)
            with source_pdf.open("wb") as output:
                writer.write(output)

            page_files = split_pdf_into_single_page_files(
                pdf_path=source_pdf,
                output_dir=pathlib.Path(temp_dir) / "pages",
            )

            self.assertEqual([page.page_number for page in page_files], [1, 2])
            self.assertEqual([page.path.name for page in page_files], ["page-0001.pdf", "page-0002.pdf"])
            self.assertEqual(len(PdfReader(str(page_files[0].path)).pages), 1)
            self.assertEqual(len(PdfReader(str(page_files[1].path)).pages), 1)

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


class _FakePageSlicedMineruClient:
    def __init__(self, *, parsed_document) -> None:
        self._parsed_document = parsed_document
        self.calls: list[dict[str, object]] = []

    def parse_pdf_by_pages(self, *, pdf_path: pathlib.Path, output_root: pathlib.Path, document_key=None, page_state_store=None):
        self.calls.append(
            {
                "method": "parse_pdf_by_pages",
                "pdf_path": pdf_path,
                "output_root": output_root,
            }
        )
        return self._parsed_document


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
