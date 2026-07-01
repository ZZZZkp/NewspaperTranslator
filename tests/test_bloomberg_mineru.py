import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.bloomberg_mineru import Block, load_blocks


def test_load_blocks_normalizes_fields():
    raw = [
        {"type": "text", "text_level": 1, "page_idx": 2,
         "bbox": [29, 60, 786, 183], "text": "A Headline"},
        {"type": "image", "page_idx": 2, "bbox": [1, 2, 3, 4],
         "img_path": "images/x.jpg"},
    ]
    blocks = load_blocks(raw)
    assert blocks[0] == Block("text", 1, 2, (29, 60, 786, 183), "A Headline", "")
    assert blocks[1] == Block("image", None, 2, (1, 2, 3, 4), "", "images/x.jpg")


def test_title_matches_containment_and_jaccard():
    from newspaper_translator.bloomberg_mineru import title_matches
    # exact after normalization
    assert title_matches("Salmon Farming, Now on Land", "Salmon Farming Now on Land")
    # candidate contains entry
    assert title_matches("The Great AI Build-Out\n(cover)", "The Great AI Build-Out")
    # token overlap >= 0.6
    assert title_matches("Andy Jassy's Plan to Launch Amazon Into the AI Age",
                         "Andy Jassys Plan to Launch Amazon Into The AI Age")
    # unrelated pull-quote does not match
    assert not title_matches(
        "You can choose to howl at the wind, but AI is not going away",
        "Salmon Farming, Now on Land")


def test_normalize_title_strips_punct_and_case():
    from newspaper_translator.bloomberg_mineru import normalize_title
    assert normalize_title("  The Great AI Build-Out! ") == "the great ai build out"


def test_parse_contents_extracts_title_folio_pairs():
    from newspaper_translator.bloomberg_mineru import Block, parse_contents, ContentsEntry
    blocks = [
        Block("text", None, 8, (0, 0, 0, 0), "Contents", ""),
        Block("text", None, 8, (0, 0, 0, 0),
              "Remarks\nHow will AI alter the economy? Ask a scarecrow\n10\n", ""),
        Block("text", None, 8, (0, 0, 0, 0), "Salmon Farming, Now on Land 21", ""),
        Block("text", None, 8, (0, 0, 0, 0), "just prose with no folio", ""),
    ]
    entries = parse_contents(blocks)
    assert ContentsEntry("How will AI alter the economy? Ask a scarecrow", 10) in entries
    assert ContentsEntry("Salmon Farming, Now on Land", 21) in entries
    assert all(e.title != "just prose with no folio" for e in entries)


def test_parse_contents_ignores_pages_after_12():
    from newspaper_translator.bloomberg_mineru import Block, parse_contents
    blocks = [Block("text", None, 20, (0, 0, 0, 0), "Late Title 55", "")]
    assert parse_contents(blocks) == []


def test_classify_pages_editorial_ad_and_park_elm_trap():
    from newspaper_translator.bloomberg_mineru import Block, classify_pages, ContentsEntry
    blocks = [
        # p0 editorial: has a folio + recurring running header "The AI Issue"
        Block("page_number", None, 0, (42, 960, 60, 974), "10", ""),
        Block("header", None, 0, (0, 0, 0, 0), "The AI Issue", ""),
        Block("text", None, 0, (29, 60, 786, 183), "body body body", ""),
        # p1 editorial: recurring running header, no folio (infographic opener)
        Block("header", None, 1, (0, 0, 0, 0), "The AI Issue", ""),
        Block("title", 2, 1, (31, 48, 672, 81), "How to Build a Data Center in Space", ""),
        # p2 AD: ParkElm trap — its "header" is ad copy, no folio, has URL/phone
        Block("header", None, 2, (403, 47, 800, 97), "PARK ELM RESIDENCES AT CENTURY PLAZA", ""),
        Block("text", None, 2, (283, 286, 900, 302), "Learn more at ParkElmCenturyPlaza.com | (310) 340-6987", ""),
        # p3 AD: explicit ADVERTISEMENT header
        Block("header", None, 3, (0, 0, 0, 0), "ADVERTISEMENT", ""),
        Block("text", None, 3, (0, 0, 0, 0), "vivo phone brand copy", ""),
    ]
    contents = [ContentsEntry("How to Build a Data Center in Space", 72)]
    kinds = classify_pages(blocks, contents)
    assert kinds[0].kind == "editorial" and kinds[0].section == "The AI Issue"
    assert kinds[1].kind == "editorial"
    assert kinds[2].kind == "ad"
    assert kinds[3].kind == "ad"


def test_detect_page_offset_votes():
    from newspaper_translator.bloomberg_mineru import Block, detect_page_offset
    blocks = [
        Block("page_number", None, 11, (0, 0, 0, 0), "10", ""),
        Block("page_number", None, 12, (0, 0, 0, 0), "11", ""),
        Block("page_number", None, 13, (0, 0, 0, 0), "12", ""),
    ]  # (page_idx+1) - folio == 2 for all three
    assert detect_page_offset(blocks) == 2


def test_find_boundaries_matches_titles_and_drops_noise():
    from newspaper_translator.bloomberg_mineru import (
        Block, ContentsEntry, PageKind, find_boundaries, Boundary,
    )
    blocks = [
        Block("title", 1, 2, (29, 60, 786, 183), "Salmon Farming, Now on Land", ""),   # 0 real
        Block("title", 2, 2, (75, 52, 156, 67), "Bad Vibes", ""),                       # 1 chart (h=15)
        Block("title", 1, 3, (26, 737, 913, 927), "Pull quote line here", ""),          # 2 pull-quote (no match)
        Block("title", 1, 4, (73, 490, 658, 883), "A $12 Billion Stash Of Critical Minerals", ""),  # 3 real
    ]
    contents = [
        ContentsEntry("Salmon Farming, Now on Land", 21),
        ContentsEntry("A $12 Billion Stash Of Critical Minerals", 24),
    ]
    page_kinds = {2: PageKind("editorial", ""), 3: PageKind("editorial", ""),
                  4: PageKind("editorial", "")}
    bounds = find_boundaries(blocks, contents, page_kinds)
    assert bounds == [
        Boundary("Salmon Farming, Now on Land", 2, 0),
        Boundary("A $12 Billion Stash Of Critical Minerals", 4, 3),
    ]


def test_find_boundaries_folio_fallback_for_missed_title():
    from newspaper_translator.bloomberg_mineru import (
        Block, ContentsEntry, PageKind, find_boundaries,
    )
    # offset = 2 (folio 20 on page_idx 21). Missed title -> anchor first editorial
    # text block on estimated page (20 + 2 - 1 = 21).
    blocks = [
        Block("page_number", None, 11, (0, 0, 0, 0), "10", ""),
        Block("page_number", None, 12, (0, 0, 0, 0), "11", ""),
        Block("page_number", None, 21, (0, 0, 0, 0), "20", ""),
        Block("text", None, 21, (29, 60, 400, 200), "Missed article body starts here", ""),
    ]
    contents = [ContentsEntry("Missed Article", 20)]
    page_kinds = {21: PageKind("editorial", "")}
    bounds = find_boundaries(blocks, contents, page_kinds)
    assert len(bounds) == 1
    assert bounds[0].page_idx == 21
    assert bounds[0].title == "Missed Article"


def test_repair_dropcap_and_trim_end_marker():
    from newspaper_translator.bloomberg_mineru import repair_dropcap, trim_end_marker
    assert repair_dropcap("B ut Jassy's biggest bet") == "But Jassy's biggest bet"
    assert repair_dropcap("T hirteen miles north") == "Thirteen miles north"
    assert trim_end_marker("...before the crowd arrived. <BW> —With Annie Lee") \
        == "...before the crowd arrived."


def test_persist_requires_mineru_client_kwarg():
    import inspect
    from newspaper_translator.article_pipeline import persist_bloomberg_edition_articles
    params = inspect.signature(persist_bloomberg_edition_articles).parameters
    assert "mineru_client" in params
    assert params["mineru_client"].default is inspect.Parameter.empty


def test_assemble_articles_builds_body_and_images(tmp_path):
    from pathlib import Path
    from newspaper_translator.bloomberg_mineru import (
        Block, Boundary, PageKind, assemble_articles,
    )
    extract = tmp_path / "extract"
    (extract / "images").mkdir(parents=True)
    (extract / "images" / "h.jpg").write_bytes(b"jpg")
    images_dir = tmp_path / "images"
    blocks = [
        Block("title", 1, 2, (29, 60, 786, 183), "Salmon Farming, Now on Land", ""),  # 0
        Block("text", None, 2, (0, 0, 0, 0), "Body one.", ""),                         # 1
        Block("image", None, 3, (0, 0, 0, 0), "", "images/h.jpg"),                     # 2
        Block("text", None, 3, (0, 0, 0, 0), "Body two. <BW> —With X", ""),            # 3
        Block("footer", None, 3, (0, 0, 0, 0), "Bloomberg Businessweek", ""),          # dropped
    ]
    boundaries = [Boundary("Salmon Farming, Now on Land", 2, 0)]
    page_kinds = {2: PageKind("editorial", "In Context"),
                  3: PageKind("editorial", "In Context")}
    articles = assemble_articles(
        blocks, boundaries, page_kinds,
        images_dir=images_dir, mineru_extract_dir=extract,
    )
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Salmon Farming, Now on Land"
    assert art.section == "In Context"
    assert art.start_page == 3  # page_idx 2 + 1
    assert "Body one." in art.body_text and "Body two." in art.body_text
    assert "<BW>" not in art.body_text
    assert "![](images/h.jpg)" in art.body_text
    assert (images_dir / "h.jpg").exists()


def test_parse_bloomberg_edition_end_to_end(tmp_path):
    from pathlib import Path
    from newspaper_translator.bloomberg_mineru import parse_bloomberg_edition
    from newspaper_translator.mineru import MineruParsedDocument

    extract = tmp_path / "out" / "doc"
    (extract / "images").mkdir(parents=True)
    (extract / "images" / "h.jpg").write_bytes(b"jpg")
    (extract / "full.md").write_text("md", encoding="utf-8")

    content_list = [
        {"type": "text", "page_idx": 1, "bbox": [0, 0, 0, 0],
         "text": "Contents\nSalmon Farming, Now on Land 21\n"},
        {"type": "page_number", "page_idx": 21, "bbox": [0, 0, 0, 0], "text": "20"},
        {"type": "title", "text_level": 1, "page_idx": 21,
         "bbox": [29, 60, 786, 183], "text": "Salmon Farming, Now on Land"},
        {"type": "text", "page_idx": 21, "bbox": [0, 0, 0, 0], "text": "Body."},
        {"type": "image", "page_idx": 21, "bbox": [0, 0, 0, 0], "img_path": "images/h.jpg"},
    ]

    class FakeClient:
        def parse_pdf(self, *, pdf_path, output_root):
            return MineruParsedDocument(
                batch_id="b", file_id="f", file_name="doc.pdf",
                markdown_path=extract / "full.md", markdown_text="md",
                content_list=tuple(content_list),
            )

    parsed = parse_bloomberg_edition(
        Path("doc.pdf"), images_dir=tmp_path / "images",
        mineru_client=FakeClient(), output_root=tmp_path / "out",
    )
    titles = [a.title for a in parsed.parse_result.articles]
    assert "Salmon Farming, Now on Land" in titles
