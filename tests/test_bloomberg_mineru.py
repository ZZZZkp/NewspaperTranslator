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
