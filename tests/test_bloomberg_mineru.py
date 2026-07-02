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
    from newspaper_translator.bloomberg_mineru import Block, classify_pages
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
    kinds = classify_pages(blocks)
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


def test_running_section_names_includes_footer_excludes_masthead():
    from newspaper_translator.bloomberg_mineru import Block, running_section_names
    blocks = [
        Block("footer", None, 24, (0,0,0,0), "In Context", ""),
        Block("footer", None, 27, (0,0,0,0), "In Context", ""),
        Block("footer", None, 24, (0,0,0,0), "Bloomberg Businessweek", ""),
        Block("footer", None, 27, (0,0,0,0), "Bloomberg Businessweek", ""),
    ]
    names = running_section_names(blocks)
    assert "in context" in names
    assert "bloomberg businessweek" not in names


def test_is_byline_detects_bullet_by():
    from newspaper_translator.bloomberg_mineru import Block, _is_byline
    assert _is_byline(Block("text", 2, 20, (0,0,0,0), "● By Jane Doe", ""))
    assert _is_byline(Block("text", 2, 53, (0,0,0,0), "○ By John Roe", ""))
    assert not _is_byline(Block("text", 1, 20, (0,0,0,0), "A Politically Fraught World Cup", ""))
    assert not _is_byline(Block("text", 2, 17, (0,0,0,0), "● KUALA LUMPUR", ""))


def test_classify_pages_positive_signal():
    from newspaper_translator.bloomberg_mineru import Block, classify_pages
    blocks = [
        # running section header on 2 pages -> section name "the ai issue"
        Block("header", None, 44, (0,0,0,0), "The AI Issue", ""),
        Block("header", None, 46, (0,0,0,0), "The AI Issue", ""),
        # p16 editorial opener: NO folio, NO running header, but HAS a byline -> editorial
        Block("text", 1, 16, (29,60,600,140), "The Summer of Our Discontent", ""),
        Block("text", 2, 16, (29,150,300,175), "● By Miles Herszenhorn", ""),
        # p10 brand ad: no folio, no running header, no byline -> ad
        Block("text", 1, 10, (40,40,400,130), "PANERAI", ""),
        # p22 brand ad with only a slogan -> ad
        Block("text", 1, 22, (40,40,400,90), "Discreet elegance.", ""),
        # p26 ad via tokens (no folio)
        Block("text", None, 26, (0,0,0,0), "Learn more at ParkElm.com | (310) 340-6987", ""),
        # p35 advertorial: ADVERTISEMENT header -> ad
        Block("header", None, 35, (0,0,0,0), "ADVERTISEMENT", ""),
        Block("text", 1, 35, (0,0,0,0), "vivo brand copy", ""),
        # p46 editorial feature page: has folio -> editorial
        Block("page_number", None, 46, (0,0,0,0), "44", ""),
        Block("text", 1, 46, (0,0,0,0), "Andy Jassy's Plan", ""),
    ]
    kinds = classify_pages(blocks)
    assert kinds[16].kind == "editorial"   # opener saved by byline
    assert kinds[46].kind == "editorial"   # folio
    assert kinds[10].kind == "ad"
    assert kinds[22].kind == "ad"
    assert kinds[26].kind == "ad"
    assert kinds[35].kind == "ad"


def test_is_pull_quote_matches_body_substring():
    from newspaper_translator.bloomberg_mineru import Block, _is_pull_quote, _body_paragraphs
    body = Block("text", None, 41, (0,0,0,0),
                 "Overall, more than one-third of all adult workers are in some way "
                 "disconnected from the organization for whom they work, according to my survey.", "")
    quote = Block("text", 1, 41, (0,0,0,0),
                  "more than one-third of all adult workers are in some way disconnected", "")
    headline = Block("text", 1, 41, (0,0,0,0), "America Is Addicted To Disposable Work", "")
    paras = _body_paragraphs([body])
    assert _is_pull_quote(quote, paras)
    assert not _is_pull_quote(headline, paras)


def test_demirror_collapses_doubled_prefix():
    from newspaper_translator.bloomberg_mineru import _demirror
    assert _demirror("The Most The Most ompellin Watches") == "The Most ompellin Watches"
    assert _demirror("A Broken A Broken Market Ins A Radical") == "A Broken Market Ins A Radical"
    assert _demirror("Salmon Farming, Now on Land") == "Salmon Farming, Now on Land"


def test_find_boundaries_enumerates_headlines_and_filters():
    from newspaper_translator.bloomberg_mineru import (
        Block, PageKind, find_boundaries, Boundary,
    )
    blocks = [
        Block("text", 1, 20, (29,60,600,110), "A Politically Fraught World Cup", ""),   #0 real (h50)
        Block("text", 2, 20, (29,120,300,150), "● By Reporter", ""),                     #1 byline (skip)
        Block("text", 2, 17, (29,700,200,716), "● KUALA LUMPUR", ""),                    #2 dateline (h16<30)
        Block("text", 1, 39, (26,737,913,927), "workers are disconnected from the org", ""), #3 pull-quote
        Block("text", None, 39, (0,0,0,0), "many workers are disconnected from the org today "
              "and it matters a great deal for the economy at large as we will see in time", ""),     #4 body (>120)
        Block("text", 1, 41, (29,60,700,183), "America Is Addicted To Disposable Work", ""), #5 real (h123)
    ]
    page_kinds = {17: PageKind("editorial",""), 20: PageKind("editorial",""),
                  39: PageKind("editorial",""), 41: PageKind("editorial","")}
    bounds = find_boundaries(blocks, page_kinds)
    assert bounds == [
        Boundary("A Politically Fraught World Cup", 20, 0),
        Boundary("America Is Addicted To Disposable Work", 41, 5),
    ]


def test_find_boundaries_joins_split_headline():
    from newspaper_translator.bloomberg_mineru import Block, PageKind, find_boundaries
    blocks = [
        Block("text", 1, 55, (29,60,400,159), "Meta Goes Big", ""),       #0 h99
        Block("text", 1, 56, (29,60,400,162), "on the Bayou", ""),        #1 h102, next page, no byline between
        Block("text", 2, 56, (29,200,300,230), "● By Author", ""),        #2 byline after join
    ]
    pk = {55: PageKind("editorial",""), 56: PageKind("editorial","")}
    bounds = find_boundaries(blocks, pk)
    assert len(bounds) == 1
    assert bounds[0].title == "Meta Goes Big on the Bayou"
    assert bounds[0].block_index == 0
