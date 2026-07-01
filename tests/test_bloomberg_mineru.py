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
