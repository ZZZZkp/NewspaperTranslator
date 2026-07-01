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
