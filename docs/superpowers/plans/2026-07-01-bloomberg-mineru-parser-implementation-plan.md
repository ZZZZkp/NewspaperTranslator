# Bloomberg MinerU Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local pypdf Bloomberg parser with a MinerU-driven one where MinerU `type:title` blocks drive article boundaries, the printed Contents page is an authoritative title whitelist, and ads are filtered at page granularity.

**Architecture:** MinerU parses the whole magazine once and returns `content_list` blocks (type, text_level, page_idx, bbox, text). Pure functions parse the Contents whitelist, classify each page editorial/ad, pick real title boundaries by fuzzy-matching titles against the whitelist, and assemble article bodies from editorial blocks in reading order. Output reuses the existing `EditionArticle`/`ParsedEdition` structures so persistence and translation downstream are unchanged.

**Tech Stack:** Python 3.11, pytest, pypdf (detection only), MinerU HTTP client (existing `mineru.py`).

## Global Constraints

- Whole-document MinerU parse (`parse_pdf`), never page-sliced, for Bloomberg.
- No local fallback: MinerU failure propagates like other MinerU papers.
- Output structures unchanged: `EditionArticle(title, section, start_page, end_page, body_text, url)`, `ParsedEdition(parse_result, debug_text)`, `build_economist_parse_result(articles)`.
- Reuse existing sha256 image de-dupe convention; body image refs are `![](images/<name>)` with files under `<debug_dir>/images/`.
- bbox is `[x0, y0, x1, y1]` scaled 0–1000.
- Parser version string bumps to `bloomberg-mineru-v1`.
- YAGNI: no non-contiguous "jump" continuation, no `◀/▶` recovery, no pdfplumber, no page-sliced Bloomberg.

---

### Task 1: Surface `content_list.json` from the MinerU zip

**Files:**
- Modify: `src/newspaper_translator/mineru.py` (add `content_list` field to `MineruParsedDocument` ~L37-44; add `load_content_list_from_dir`; populate in `parse_pdf` ~L155-178)
- Test: `tests/test_mineru_content_list.py`

**Interfaces:**
- Produces: `load_content_list_from_dir(extraction_dir: Path) -> tuple[dict, ...]`
- Produces: `MineruParsedDocument.content_list: tuple[dict, ...]` (default `()`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mineru_content_list.py
import json
from pathlib import Path

from newspaper_translator.mineru import load_content_list_from_dir


def test_load_content_list_from_dir_reads_the_json(tmp_path: Path):
    (tmp_path / "abc_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "hi", "page_idx": 0}]),
        encoding="utf-8",
    )
    blocks = load_content_list_from_dir(tmp_path)
    assert blocks == ({"type": "text", "text": "hi", "page_idx": 0},)


def test_load_content_list_from_dir_missing_returns_empty(tmp_path: Path):
    assert load_content_list_from_dir(tmp_path) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mineru_content_list.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_content_list_from_dir'`

- [ ] **Step 3: Implement**

Add near the top-level helpers in `mineru.py` (module scope):

```python
def load_content_list_from_dir(extraction_dir: Path) -> tuple[dict, ...]:
    matches = sorted(Path(extraction_dir).rglob("*_content_list.json"))
    if not matches:
        return ()
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    return tuple(item for item in data if isinstance(item, dict))
```

Add the field to `MineruParsedDocument`:

```python
@dataclass(frozen=True)
class MineruParsedDocument:
    batch_id: str
    file_id: str
    file_name: str
    markdown_path: Path
    markdown_text: str
    pages: tuple["MineruParsedPage", ...] = ()
    content_list: tuple[dict, ...] = ()
```

In `parse_pdf`, after `markdown_path, markdown_text = self._extract_full_markdown(...)`, add:

```python
        content_list = load_content_list_from_dir(Path(markdown_path).parent)
```

and pass `content_list=content_list` into the returned `MineruParsedDocument(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mineru_content_list.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/mineru.py tests/test_mineru_content_list.py
git commit -m "feat: surface content_list.json from MinerU parse_pdf"
```

---

### Task 2: `Block` model and `load_blocks`

**Files:**
- Create: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Produces: `Block(type: str, text_level: int | None, page_idx: int, bbox: tuple[int, int, int, int], text: str, img_path: str)`
- Produces: `load_blocks(content_list: list[dict]) -> list[Block]`

Note: all new pure functions live in the new module `bloomberg_mineru.py`. The existing `bloomberg_edition.py` is left untouched until Task 8 swaps the orchestrator over.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bloomberg_mineru.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newspaper_translator.bloomberg_mineru'`

- [ ] **Step 3: Implement**

```python
# src/newspaper_translator/bloomberg_mineru.py
"""MinerU-driven Bloomberg Businessweek parser.

Replaces the local pypdf contents-folio parser. MinerU type:title blocks drive
article boundaries; the printed Contents page is an authoritative title
whitelist; ads are filtered at page granularity via the editorial fingerprint.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    type: str
    text_level: int | None
    page_idx: int
    bbox: tuple[int, int, int, int]
    text: str
    img_path: str


def load_blocks(content_list: list[dict]) -> list[Block]:
    blocks: list[Block] = []
    for item in content_list:
        bbox = item.get("bbox") or [0, 0, 0, 0]
        blocks.append(
            Block(
                type=str(item.get("type") or ""),
                text_level=item.get("text_level"),
                page_idx=int(item.get("page_idx") or 0),
                bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                text=str(item.get("text") or ""),
                img_path=str(item.get("img_path") or ""),
            )
        )
    return blocks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: add Block model and load_blocks for Bloomberg MinerU parser"
```

---

### Task 3: Title normalization and fuzzy matching

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Produces: `normalize_title(text: str) -> str`
- Produces: `title_matches(candidate: str, entry_title: str) -> bool` (normalized-substring containment OR token-set Jaccard ≥ 0.6)

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "title_matches or normalize_title" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
import re
import unicodedata

_PUNCT_RE = re.compile(r"[^0-9a-z]+")


def normalize_title(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return _PUNCT_RE.sub(" ", folded).strip()


def title_matches(candidate: str, entry_title: str) -> bool:
    cand = normalize_title(candidate)
    entry = normalize_title(entry_title)
    if not cand or not entry:
        return False
    if entry in cand or cand in entry:
        return True
    cand_tokens = set(cand.split())
    entry_tokens = set(entry.split())
    if not cand_tokens or not entry_tokens:
        return False
    overlap = cand_tokens & entry_tokens
    union = cand_tokens | entry_tokens
    return len(overlap) / len(union) >= 0.6
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "title_matches or normalize_title" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: add title normalization and fuzzy matching"
```

---

### Task 4: `parse_contents` — Contents whitelist

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`
- Produces: `ContentsEntry(title: str, folio: int)` (folio 0 when unknown)
- Produces: `parse_contents(blocks: list[Block]) -> list[ContentsEntry]`

Contents blocks put a title line, then the folio on its own bare-number line
(observed: `"Remarks\nHow will AI alter the economy? Ask a scarecrow\n10\n..."`).
Also handle a trailing folio on the same line (`"Title 42"`). Scan only the
first 12 pages. Section-name lines (single word from a small known set) are
skipped as titles.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k parse_contents -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
_CONTENTS_SCAN_PAGES = 12
_TRAILING_FOLIO_RE = re.compile(r"^(?P<title>.*\S)\s+(?P<folio>\d{1,3})$")
_BARE_FOLIO_RE = re.compile(r"^(?P<folio>\d{1,3})$")
_SECTION_WORDS = {"remarks", "in context", "in view", "pursuits",
                  "exit strategy", "contents", "contributors", "cover"}


@dataclass(frozen=True)
class ContentsEntry:
    title: str
    folio: int


def _clean_contents_title(title: str) -> str:
    # Drop a leading section label token if present ("Remarks", "In View", ...).
    stripped = title.strip()
    if normalize_title(stripped) in _SECTION_WORDS:
        return ""
    return stripped


def parse_contents(blocks: list[Block]) -> list[ContentsEntry]:
    entries: list[ContentsEntry] = []
    seen: set[str] = set()

    def add(title: str, folio: int) -> None:
        clean = _clean_contents_title(title)
        key = normalize_title(clean)
        if not clean or not key or key in seen:
            return
        seen.add(key)
        entries.append(ContentsEntry(title=clean, folio=folio))

    for block in blocks:
        if block.page_idx >= _CONTENTS_SCAN_PAGES:
            continue
        if block.type not in ("text", "paragraph", "title"):
            continue
        lines = [ln.strip() for ln in block.text.splitlines() if ln.strip()]
        prev_title = ""
        for line in lines:
            trailing = _TRAILING_FOLIO_RE.match(line)
            bare = _BARE_FOLIO_RE.match(line)
            if bare and prev_title:
                add(prev_title, int(bare.group("folio")))
                prev_title = ""
            elif trailing:
                add(trailing.group("title"), int(trailing.group("folio")))
                prev_title = ""
            elif normalize_title(line) in _SECTION_WORDS:
                prev_title = ""
            else:
                prev_title = line
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k parse_contents -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: add parse_contents Contents whitelist extraction"
```

---

### Task 5: `classify_pages` — editorial/ad + section

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `normalize_title`
- Produces: `PageKind(kind: str, section: str)` where `kind in {"editorial", "ad"}`
- Produces: `running_section_names(blocks: list[Block]) -> set[str]` (normalized header texts appearing on ≥2 distinct pages)
- Produces: `classify_pages(blocks: list[Block], contents: list[ContentsEntry]) -> dict[int, PageKind]`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k classify_pages -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
_AD_TOKEN_RE = re.compile(
    r"(\b[\w-]+\.(?:com|net|org)\b|\(\d{3}\)\s?\d{3}|\bFINRA\b|\bSIPC\b|"
    r"Member\s*[-–]\s*NYSE|Past performance|marketing purposes|"
    r"informational purposes|BOOK NOW|Learn more at)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PageKind:
    kind: str
    section: str


def running_section_names(blocks: list[Block]) -> set[str]:
    pages_by_header: dict[str, set[int]] = {}
    for block in blocks:
        if block.type in ("header", "page_header") and block.text.strip():
            key = normalize_title(block.text)
            if key:
                pages_by_header.setdefault(key, set()).add(block.page_idx)
    return {key for key, pages in pages_by_header.items() if len(pages) >= 2}


def classify_pages(
    blocks: list[Block], contents: list[ContentsEntry]
) -> dict[int, PageKind]:
    section_names = running_section_names(blocks)
    by_page: dict[int, list[Block]] = {}
    for block in blocks:
        by_page.setdefault(block.page_idx, []).append(block)

    result: dict[int, PageKind] = {}
    for page_idx, items in by_page.items():
        headers = [b for b in items if b.type in ("header", "page_header")]
        running = next(
            (b.text.strip() for b in headers
             if normalize_title(b.text) in section_names),
            "",
        )
        has_folio = any(b.type == "page_number" for b in items)
        page_text = " ".join(b.text for b in items)
        has_advertisement = any(
            normalize_title(b.text) == "advertisement" for b in headers
        )
        editorial = has_folio or bool(running)

        if editorial and not has_advertisement:
            result[page_idx] = PageKind("editorial", running)
            continue
        if has_advertisement or _AD_TOKEN_RE.search(page_text):
            result[page_idx] = PageKind("ad", "")
            continue
        # Fallback: non-editorial, no ad token. Keep only if it carries a
        # Contents-matching title; otherwise treat as a brand full-page ad.
        titles = [b.text for b in items if b.text_level]
        if any(title_matches(t, e.title) for t in titles for e in contents):
            result[page_idx] = PageKind("editorial", running)
        else:
            result[page_idx] = PageKind("ad", "")
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k classify_pages -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: add classify_pages editorial/ad fingerprint"
```

---

### Task 6: `find_boundaries` — title blocks to real boundaries

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `ContentsEntry`, `PageKind`, `title_matches`
- Produces: `detect_page_offset(blocks: list[Block]) -> int | None` (mode of `(page_idx+1) - printed_folio` over `page_number` blocks; needs ≥3 agreeing votes)
- Produces: `Boundary(title: str, page_idx: int, block_index: int)`
- Produces: `find_boundaries(blocks: list[Block], contents: list[ContentsEntry], page_kinds: dict[int, PageKind]) -> list[Boundary]`

Rules: candidate = `type == "title"` block with bbox height ≥ 22 on an editorial
page that fuzzy-matches a Contents entry. `block_index` is the position in the
`blocks` list. Folio fallback: any Contents entry with no matched candidate gets
a boundary at the first editorial text block on its estimated page
(`folio + offset - 1`, 0-based page_idx). Result sorted by `block_index`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "find_boundaries or detect_page_offset" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
from collections import Counter

_MIN_TITLE_HEIGHT = 22
_MIN_OFFSET_VOTES = 3


def detect_page_offset(blocks: list[Block]) -> int | None:
    votes: Counter[int] = Counter()
    for block in blocks:
        if block.type == "page_number" and block.text.strip().isdigit():
            votes[(block.page_idx + 1) - int(block.text.strip())] += 1
    if not votes:
        return None
    offset, count = votes.most_common(1)[0]
    return offset if count >= _MIN_OFFSET_VOTES else None


@dataclass(frozen=True)
class Boundary:
    title: str
    page_idx: int
    block_index: int


def find_boundaries(
    blocks: list[Block],
    contents: list[ContentsEntry],
    page_kinds: dict[int, PageKind],
) -> list[Boundary]:
    bounds: list[Boundary] = []
    matched_entries: set[str] = set()

    for index, block in enumerate(blocks):
        if block.type != "title":
            continue
        if (block.bbox[3] - block.bbox[1]) < _MIN_TITLE_HEIGHT:
            continue
        if page_kinds.get(block.page_idx, PageKind("ad", "")).kind != "editorial":
            continue
        entry = next((e for e in contents if title_matches(block.text, e.title)), None)
        if entry is None:
            continue
        key = normalize_title(entry.title)
        if key in matched_entries:
            continue
        matched_entries.add(key)
        bounds.append(Boundary(entry.title, block.page_idx, index))

    # Folio fallback for entries MinerU never surfaced as a title block.
    offset = detect_page_offset(blocks)
    if offset is not None:
        for entry in contents:
            if normalize_title(entry.title) in matched_entries or entry.folio <= 0:
                continue
            target_page = entry.folio + offset - 1
            for index, block in enumerate(blocks):
                if (block.page_idx == target_page
                        and block.type in ("text", "paragraph")
                        and page_kinds.get(block.page_idx, PageKind("ad", "")).kind
                        == "editorial"):
                    matched_entries.add(normalize_title(entry.title))
                    bounds.append(Boundary(entry.title, target_page, index))
                    break

    bounds.sort(key=lambda b: b.block_index)
    return bounds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "find_boundaries or detect_page_offset" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: add find_boundaries with folio fallback"
```

---

### Task 7: `assemble_articles` — body, drop-cap, end-mark, images

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `Boundary`, `PageKind`, `EditionArticle` (from `economist_edition`)
- Produces: `repair_dropcap(text: str) -> str`
- Produces: `trim_end_marker(text: str) -> str`
- Produces: `assemble_articles(blocks: list[Block], boundaries: list[Boundary], page_kinds: dict[int, PageKind], *, images_dir: Path, mineru_extract_dir: Path) -> list[EditionArticle]`

Body = editorial text blocks strictly between a boundary's `block_index` and the
next boundary's `block_index` (last boundary runs to end). `start_page` =
boundary.page_idx + 1 (1-based). `end_page` = next boundary.page_idx + 1 (or last
block page + 2). Images/charts copied from `mineru_extract_dir/<img_path>` into
`images_dir`, appended as `![](images/<name>)`.

- [ ] **Step 1: Write the failing test**

```python
def test_repair_dropcap_and_trim_end_marker():
    from newspaper_translator.bloomberg_mineru import repair_dropcap, trim_end_marker
    assert repair_dropcap("B ut Jassy's biggest bet") == "But Jassy's biggest bet"
    assert repair_dropcap("T hirteen miles north") == "Thirteen miles north"
    assert trim_end_marker("...before the crowd arrived. <BW> —With Annie Lee") \
        == "...before the crowd arrived."


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "assemble or dropcap or end_marker" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
import shutil
from pathlib import Path

from newspaper_translator.economist_edition import EditionArticle

# Exclude A and I so standalone English words ("A dog", "I think") are not merged.
_DROPCAP_RE = re.compile(r"^([B-HJ-Z])\s+([a-z])")
_END_MARKER_RE = re.compile(r"\s*<BW>.*$", re.DOTALL)


def repair_dropcap(text: str) -> str:
    return _DROPCAP_RE.sub(r"\1\2", text)


def trim_end_marker(text: str) -> str:
    return _END_MARKER_RE.sub("", text).rstrip()


def _copy_image(img_path: str, images_dir: Path, mineru_extract_dir: Path) -> str:
    name = Path(img_path).name
    source = Path(mineru_extract_dir) / img_path
    if not source.exists():
        return ""
    images_dir.mkdir(parents=True, exist_ok=True)
    destination = images_dir / name
    if not destination.exists():
        shutil.copyfile(source, destination)
    return f"images/{name}"


def assemble_articles(
    blocks: list[Block],
    boundaries: list[Boundary],
    page_kinds: dict[int, PageKind],
    *,
    images_dir: Path,
    mineru_extract_dir: Path,
) -> list[EditionArticle]:
    articles: list[EditionArticle] = []
    for position, boundary in enumerate(boundaries):
        start = boundary.block_index + 1
        end = (
            boundaries[position + 1].block_index
            if position + 1 < len(boundaries)
            else len(blocks)
        )
        text_parts: list[str] = []
        image_refs: list[str] = []
        last_page = boundary.page_idx
        for block in blocks[start:end]:
            if page_kinds.get(block.page_idx, PageKind("ad", "")).kind != "editorial":
                continue
            last_page = max(last_page, block.page_idx)
            if block.type in ("text", "paragraph"):
                text_parts.append(repair_dropcap(block.text.strip()))
            elif block.type in ("image", "chart") and block.img_path:
                ref = _copy_image(block.img_path, images_dir, mineru_extract_dir)
                if ref:
                    image_refs.append(ref)
        body = trim_end_marker("\n\n".join(p for p in text_parts if p))
        if image_refs:
            body = body + "\n\n" + "\n".join(f"![]({ref})" for ref in image_refs)
        if not body.strip():
            continue
        end_page = (
            boundaries[position + 1].page_idx + 1
            if position + 1 < len(boundaries)
            else last_page + 2
        )
        articles.append(
            EditionArticle(
                title=boundary.title,
                section=page_kinds.get(boundary.page_idx, PageKind("editorial", "")).section,
                start_page=boundary.page_idx + 1,
                end_page=end_page,
                body_text=body,
                url="",
            )
        )
    return articles
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "assemble or dropcap or end_marker" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: add assemble_articles body/image assembly"
```

---

### Task 8: Orchestrator + detection, retire the old parser

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (add `parse_bloomberg_edition`, `detect_bloomberg_edition`, `BLOOMBERG_EDITION_PARSER_VERSION`)
- Test: `tests/test_bloomberg_mineru.py`

Note: the old `bloomberg_edition.py` is left in place (still imported by
`article_pipeline.py`) and is deleted in Task 9 after the imports are swapped, so
every commit stays green.

**Interfaces:**
- Consumes: everything above; `MineruParsedDocument` (has `.content_list`, `.markdown_path`)
- Produces: `parse_bloomberg_edition(pdf_path, *, images_dir: Path, mineru_client, output_root: Path) -> ParsedEdition`
- Produces: `detect_bloomberg_edition(pdf_path) -> bool`
- Produces: `BLOOMBERG_EDITION_PARSER_VERSION = "bloomberg-mineru-v1"`

`parse_bloomberg_edition` calls `mineru_client.parse_pdf(pdf_path=pdf_path,
output_root=output_root)`, then `load_blocks → parse_contents → classify_pages →
find_boundaries → assemble_articles`. `mineru_extract_dir =
Path(parsed.markdown_path).parent`. Raises `ValueError` if contents empty or 0
articles. `debug_text` includes a soft warning when
`len(articles) < 0.6 * len(contents)`.

- [ ] **Step 1: Write the failing test (fake mineru_client)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k parse_bloomberg_edition -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement orchestrator + detection**

```python
from newspaper_translator.economist_edition import (
    ParsedEdition,
    build_economist_parse_result,
)
from pypdf import PdfReader

BLOOMBERG_EDITION_PARSER_VERSION = "bloomberg-mineru-v1"
_DETECT_SCAN_PAGES = 15


def parse_bloomberg_edition(
    pdf_path,
    *,
    images_dir: Path,
    mineru_client,
    output_root: Path,
) -> ParsedEdition:
    parsed = mineru_client.parse_pdf(pdf_path=Path(pdf_path), output_root=Path(output_root))
    blocks = load_blocks(list(parsed.content_list))
    contents = parse_contents(blocks)
    if not contents:
        raise ValueError("Bloomberg Contents page not found in MinerU output")
    page_kinds = classify_pages(blocks, contents)
    boundaries = find_boundaries(blocks, contents, page_kinds)
    mineru_extract_dir = Path(parsed.markdown_path).parent
    articles = assemble_articles(
        blocks, boundaries, page_kinds,
        images_dir=images_dir, mineru_extract_dir=mineru_extract_dir,
    )
    if not articles:
        raise ValueError("Bloomberg parse produced no articles")

    debug_lines = [
        f"<!-- ARTICLE: {a.title} | section={a.section} "
        f"| pages={a.start_page}-{a.end_page - 1} -->\n{a.body_text}\n"
        for a in articles
    ]
    if len(articles) < 0.6 * len(contents):
        debug_lines.insert(
            0,
            f"<!-- WARNING: {len(articles)} articles from "
            f"{len(contents)} Contents entries; MinerU may have missed titles -->",
        )
    return ParsedEdition(
        parse_result=build_economist_parse_result(articles),
        debug_text="\n".join(debug_lines),
    )


def _page_text(reader, index: int) -> str:
    try:
        return reader.pages[index].extract_text() or ""
    except Exception:  # noqa: BLE001
        return ""


def detect_bloomberg_edition(pdf_path) -> bool:
    try:
        reader = PdfReader(str(pdf_path))
        producer = str((reader.metadata or {}).get("/Producer") or "").lower()
        sample = "".join(
            _page_text(reader, i)
            for i in range(min(_DETECT_SCAN_PAGES, len(reader.pages)))
        )
        if "bloomberg businessweek" not in sample.lower():
            return False
        if "calibre" in producer:
            return False
        return "Contents" in sample
    except Exception:  # noqa: BLE001
        return False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -v`
Expected: PASS (all). The old `bloomberg_edition.py` is still present, so the
rest of the suite is unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py
git commit -m "feat: add Bloomberg MinerU orchestrator and detection"
```

---

### Task 9: Wire the pipeline and routing

**Files:**
- Modify: `src/newspaper_translator/article_pipeline.py` (imports ~L18-20; `persist_bloomberg_edition_articles` ~L206-219)
- Modify: `src/newspaper_translator/document_processing.py` (import ~L12-16; Bloomberg routing ~L1899-1905)
- Test: `tests/test_document_processing_economist_routing.py` (extend), `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `parse_bloomberg_edition(..., mineru_client=..., output_root=...)`
- Produces: `persist_bloomberg_edition_articles(..., mineru_client, ...)` (new required kw-arg)

- [ ] **Step 1: Update imports in `article_pipeline.py`**

Change the import block (currently `from newspaper_translator.bloomberg_edition import (...)`):

```python
from newspaper_translator.bloomberg_mineru import (
    BLOOMBERG_EDITION_PARSER_VERSION,
    parse_bloomberg_edition,
)
```

- [ ] **Step 2: Thread `mineru_client` through `persist_bloomberg_edition_articles`**

Add `mineru_client` to the signature and the `parse_bloomberg_edition` call.
Change the signature (add param after `output_root`):

```python
def persist_bloomberg_edition_articles(
    *,
    database_url: str,
    document_key: str,
    output_root: Path,
    mineru_client,
    parser_name: str = "bloomberg-edition",
    parser_version: str = BLOOMBERG_EDITION_PARSER_VERSION,
):
```

Change the parse call (currently `parse_bloomberg_edition(Path(document.raw_path), images_dir=images_dir)`):

```python
    parsed_edition = parse_bloomberg_edition(
        Path(document.raw_path),
        images_dir=images_dir,
        mineru_client=mineru_client,
        output_root=debug_dir,
    )
```

- [ ] **Step 3: Update `document_processing.py`**

Change the import (currently `from newspaper_translator.bloomberg_edition import detect_bloomberg_edition`):

```python
from newspaper_translator.bloomberg_mineru import detect_bloomberg_edition
```

Change the Bloomberg routing call (~L1900) to pass the client:

```python
        if detect_bloomberg_edition(Path(document.raw_path)):
            persist_bloomberg_edition_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=Path(output_root),
                mineru_client=mineru_client,
            )
            return
```

- [ ] **Step 4: Write a routing regression test**

```python
# tests/test_bloomberg_mineru.py  (append)
def test_persist_requires_mineru_client_kwarg():
    import inspect
    from newspaper_translator.article_pipeline import persist_bloomberg_edition_articles
    params = inspect.signature(persist_bloomberg_edition_articles).parameters
    assert "mineru_client" in params
    assert params["mineru_client"].default is inspect.Parameter.empty
```

- [ ] **Step 5: Delete the retired module and its tests**

Now that nothing imports it, remove the old pypdf parser:

```bash
git rm src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
```

- [ ] **Step 6: Run the test suite**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py tests/test_document_processing_economist_routing.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/newspaper_translator/article_pipeline.py src/newspaper_translator/document_processing.py tests/test_bloomberg_mineru.py
git commit -m "feat: route Bloomberg persistence through MinerU client, retire pypdf parser"
```

---

### Task 10: Full-suite verification and optional live test

**Files:**
- Test: `tests/test_bloomberg_mineru_live.py` (opt-in)

**Interfaces:** none new.

- [ ] **Step 1: Add opt-in live integration test**

```python
# tests/test_bloomberg_mineru_live.py
import os
from pathlib import Path

import pytest

RUN_LIVE = os.environ.get("BLOOMBERG_LIVE_PDF")


@pytest.mark.skipif(not RUN_LIVE, reason="set BLOOMBERG_LIVE_PDF to run")
def test_live_full_magazine(tmp_path):
    from newspaper_translator.config import MineruSettings
    from newspaper_translator.mineru import MineruClient
    from newspaper_translator.bloomberg_mineru import parse_bloomberg_edition

    client = MineruClient(settings=MineruSettings.from_env(os.environ))
    parsed = parse_bloomberg_edition(
        Path(RUN_LIVE), images_dir=tmp_path / "images",
        mineru_client=client, output_root=tmp_path / "out",
    )
    assert len(parsed.parse_result.articles) >= 10
    for article in parsed.parse_result.articles:
        assert "Learn more at" not in article.body_text  # no ad leakage
```

- [ ] **Step 2: Run the whole unit suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: PASS, no references to the deleted `bloomberg_edition` module.

- [ ] **Step 3: Grep for stale imports**

Run: `grep -rn "bloomberg_edition" src/ tests/`
Expected: no matches (all migrated to `bloomberg_mineru`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_bloomberg_mineru_live.py
git commit -m "test: add opt-in live Bloomberg MinerU integration test"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = content_list surfacing; Tasks 2–7 = load_blocks, parse_contents, classify_pages (ad fingerprint + ParkElm trap + ADVERTISEMENT), find_boundaries (bbox filter + fuzzy match + folio fallback), assemble_articles (stitch, drop-cap, `<BW>`, images); Task 8 = orchestrator + detection (offset requirement removed) + retire old parser; Task 9 = pipeline wiring; Task 10 = verification + soft sanity-check via `debug_text` warning (Task 8). All spec sections mapped.
- **Types consistent:** `Block`, `ContentsEntry`, `PageKind`, `Boundary`, `EditionArticle` used with the same fields across tasks.
- **No local fallback / whole-doc parse / version bump / YAGNI** enforced per Global Constraints.
