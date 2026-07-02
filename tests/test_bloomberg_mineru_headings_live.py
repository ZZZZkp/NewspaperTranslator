# tests/test_bloomberg_mineru_headings_live.py
import json
import os
import pathlib
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

CONTENT_LIST = os.environ.get("BLOOMBERG_CONTENT_LIST")

# The 19 front/feature headlines the parser must recover on the June 2026 issue.
EXPECTED = [
    "What a Smart Scarecrow",
    "The Summer of Our Discontent",
    "A Politically Fraught World Cup",
    "Salmon Farming, Now on Land",
    "Billion Stash Of Critical Minerals",
    "Risky Retirements Down Under",
    "America Is Addicted To Disposable Work",
    "The Great AI Build-Out",
    "Andy Jassy",
    "The Building Blocks of the AI Boom",
    "Meta Goes Big on the Bayou",
    "Cable Projects Are Getting Tangled Up",
    "The Insider On the Outs",
    "How to Build a Data Center in Space",
    "The Mac Mini Is Powering the Boom in AI Agents",
    "The AI Revival Of Three Mile Island",
    "The AI Boom Is a Dilemma for Retail Investors",
    "Wanna Merge?",
]
FORBIDDEN = [  # teaser / ad / pull-quote strings that must NOT be titles
    "Seeking a better way to farm salmon",
    "Anxious Australians are turning to DIY",
    "Learn more at",
    "PANERAI",
    "Discreet elegance",
    "not necessarily dedicated to MAGA",
]


@pytest.mark.skipif(not CONTENT_LIST, reason="set BLOOMBERG_CONTENT_LIST to run")
def test_headlines_recovered_from_real_issue():
    from newspaper_translator.bloomberg_mineru import (
        load_blocks, classify_pages, find_boundaries,
    )
    data = json.loads(Path(CONTENT_LIST).read_text(encoding="utf-8"))
    blocks = load_blocks(data)
    boundaries = find_boundaries(blocks, classify_pages(blocks))
    titles = [b.title for b in boundaries]
    joined = " || ".join(titles)
    missing = [e for e in EXPECTED if e not in joined]
    assert not missing, f"missing headlines: {missing}"
    for bad in FORBIDDEN:
        assert bad not in joined, f"forbidden title present: {bad}"
