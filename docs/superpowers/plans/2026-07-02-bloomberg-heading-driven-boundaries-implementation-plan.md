# Bloomberg Heading-Driven Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Bloomberg MinerU parser so article boundaries come from the real `text_level` headings (not the broken `type=="title"` filter or Contents teasers), producing correct printed headlines for the magazine's front/feature articles.

**Architecture:** Rework three functions in `src/newspaper_translator/bloomberg_mineru.py`. `classify_pages` marks a page `ad` only on positive evidence (byline-aware, so folio-less editorial openers survive). `find_boundaries` enumerates `text_level` headings on editorial pages, filters ads/quotes/banners/pull-quotes/bylines, keeps the topmost per page, conservatively joins split heading lines, and de-mirrors VLM garble. `assemble_articles` is unchanged. Contents parsing is retained only for the sanity-count warning.

**Tech Stack:** Python 3.11, pytest. No new dependencies.

## Global Constraints

- The heading field in MinerU `content_list.json` is `text_level` on `type=="text"` blocks; `type=="title"` does NOT appear there — never filter on `type=="title"`.
- Never lexically match Contents entries against printed headlines (Contents entries are teasers).
- `assemble_articles` and the `Boundary`/`EditionArticle`/`ParsedEdition` shapes stay unchanged.
- `Block` fields: `type: str`, `text_level: int | None`, `page_idx: int`, `bbox: tuple[int,int,int,int]`, `text: str`, `img_path: str`. Heading height = `bbox[3] - bbox[1]`.
- Thresholds (tune only if a test needs it): headline height ≥ 30; split-join same-or-next page + height delta < 40; pull-quote min length 15, page window ±2.
- Acceptance target = the June 2026 issue's 19 front/feature headlines with correct text, no teaser/ad/pull-quote/section-banner titles. Pursuits back-of-book is best-effort (documented follow-up).
- Every commit keeps the full suite green (`.venv/bin/pytest -q`).

---

### Task 1: Footer-aware section names + byline helper

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (`running_section_names`)
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `normalize_title`
- Produces: `running_section_names(blocks) -> set[str]` (now also scans `footer`/`page_footer`; excludes the `"bloomberg businessweek"` masthead)
- Produces: `_is_byline(block: Block) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "running_section_names_includes_footer or is_byline" -v`
Expected: FAIL (`_is_byline` ImportError; masthead assertion fails).

- [ ] **Step 3: Implement**

Replace the existing `running_section_names` and add `_is_byline`:

```python
_MASTHEAD = "bloomberg businessweek"


def running_section_names(blocks: list[Block]) -> set[str]:
    pages_by_header: dict[str, set[int]] = {}
    for block in blocks:
        if block.type in ("header", "page_header", "footer", "page_footer") and block.text.strip():
            key = normalize_title(block.text)
            if key and key != _MASTHEAD:
                pages_by_header.setdefault(key, set()).add(block.page_idx)
    return {key for key, pages in pages_by_header.items() if len(pages) >= 2}


def _is_byline(block: Block) -> bool:
    text = block.text.strip()
    return text[:1] in ("●", "○") and "by" in normalize_title(text)[:6]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "running_section_names or is_byline" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: footer-aware section names + byline helper"
```

---

### Task 2: Positive-signal `classify_pages`

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (`classify_pages`)
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (`parse_bloomberg_edition` — update the `classify_pages` call)
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `PageKind`, `running_section_names`, `_is_byline`, `normalize_title`, `_AD_TOKEN_RE`
- Produces: `classify_pages(blocks: list[Block]) -> dict[int, PageKind]` (drops the old `contents` parameter)

Old rule marked a page `ad` on absence of folio+header, wrongly dropping folio-less editorial openers. New rule marks `ad` only on positive evidence.

- [ ] **Step 1: Write the failing test**

```python
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
        Block("text", 1, 46, (0,0,0,0), "Andy Jassy’s Plan", ""),
    ]
    kinds = classify_pages(blocks)
    assert kinds[16].kind == "editorial"   # opener saved by byline
    assert kinds[46].kind == "editorial"   # folio
    assert kinds[10].kind == "ad"
    assert kinds[22].kind == "ad"
    assert kinds[26].kind == "ad"
    assert kinds[35].kind == "ad"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k classify_pages_positive_signal -v`
Expected: FAIL (old signature requires `contents`; p16 wrongly `ad`).

- [ ] **Step 3: Implement**

Replace `classify_pages` entirely:

```python
def classify_pages(blocks: list[Block]) -> dict[int, PageKind]:
    section_names = running_section_names(blocks)
    by_page: dict[int, list[Block]] = {}
    for block in blocks:
        by_page.setdefault(block.page_idx, []).append(block)

    result: dict[int, PageKind] = {}
    for page_idx, items in by_page.items():
        has_folio = any(b.type == "page_number" for b in items)
        has_byline = any(_is_byline(b) for b in items)
        running = next(
            (b.text.strip() for b in items
             if b.type in ("header", "page_header", "footer", "page_footer")
             and normalize_title(b.text) in section_names),
            "",
        )
        page_text = " ".join(b.text for b in items)
        is_advertorial = any(
            b.type in ("header", "page_header") and normalize_title(b.text) == "advertisement"
            for b in items
        )
        if is_advertorial:
            result[page_idx] = PageKind("ad", "")
        elif not has_folio and _AD_TOKEN_RE.search(page_text):
            result[page_idx] = PageKind("ad", "")
        elif not has_folio and not running and not has_byline:
            result[page_idx] = PageKind("ad", "")
        else:
            result[page_idx] = PageKind("editorial", running)
    return result
```

In `parse_bloomberg_edition`, change `page_kinds = classify_pages(blocks, contents)` to:

```python
    page_kinds = classify_pages(blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "classify_pages" -v`
Expected: PASS. Note: the old `test_classify_pages_editorial_ad_and_park_elm_trap` calls `classify_pages(blocks, contents)` — update that call to `classify_pages(blocks)` (drop the `contents` arg) and keep its assertions.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: positive-signal byline-aware ad classification"
```

---

### Task 3: Pull-quote and de-mirror helpers

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py`
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `normalize_title`
- Produces: `_body_paragraphs(blocks: list[Block]) -> list[Block]`
- Produces: `_is_pull_quote(block: Block, paragraphs: list[Block]) -> bool`
- Produces: `_demirror(text: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
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
    assert _demirror("A Broken A Broken Market Ins A Radical") == "Broken Market Ins A Radical"
    assert _demirror("Salmon Farming, Now on Land") == "Salmon Farming, Now on Land"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "pull_quote or demirror" -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement**

```python
def _body_paragraphs(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.type in ("text", "paragraph") and not b.text_level and len(b.text) > 120]


def _is_pull_quote(block: Block, paragraphs: list[Block]) -> bool:
    needle = normalize_title(block.text)
    if len(needle) < 15:
        return False
    return any(
        needle in normalize_title(p.text)
        for p in paragraphs
        if abs(p.page_idx - block.page_idx) <= 2
    )


def _demirror(text: str) -> str:
    words = text.split()
    for k in (3, 2, 1):
        if len(words) >= 2 * k and words[:k] == words[k:2 * k]:
            return " ".join(words[k:])
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k "pull_quote or demirror" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: pull-quote detection and de-mirror helpers"
```

---

### Task 4: Heading-driven `find_boundaries`

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (`find_boundaries`)
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (`parse_bloomberg_edition` — update the `find_boundaries` call)
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: `Block`, `PageKind`, `Boundary`, `running_section_names`, `normalize_title`, `_is_byline`, `_body_paragraphs`, `_is_pull_quote`, `_demirror`
- Produces: `find_boundaries(blocks: list[Block], page_kinds: dict[int, PageKind]) -> list[Boundary]` (drops the old `contents` parameter and the folio fallback)

Rules: candidate = `text_level` block on an editorial page, height ≥ 30, non-empty, not starting with `●/○/quote/(`, not a bare number, not a section name / known rubric, not a pull-quote. Keep the topmost candidate per page. Conservatively join a following kept heading (same-or-next page, height delta < 40, no byline between). De-mirror titles. `Boundary.title` = heading text, `block_index` = its index.

- [ ] **Step 1: Write the failing tests**

```python
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
              "and it matters a great deal for the economy at large as we will see", ""),     #4 body
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k find_boundaries -v`
Expected: FAIL (old signature requires `contents`; old logic filters `type=="title"`).

- [ ] **Step 3: Implement**

Replace `find_boundaries` entirely (delete the old body, the `detect_page_offset` call, and the folio-fallback loop):

```python
_MIN_HEADLINE_HEIGHT = 30
_KNOWN_RUBRICS = {
    "contributors", "pursuits", "in context", "pursuits picks",
    "pricing the stockpile",
}
_TITLE_SKIP_PREFIX = ("●", "○", '"', "“", "”", "(")


def find_boundaries(
    blocks: list[Block], page_kinds: dict[int, PageKind]
) -> list[Boundary]:
    section_names = running_section_names(blocks)
    paragraphs = _body_paragraphs(blocks)

    candidates: list[tuple[int, Block]] = []
    for index, block in enumerate(blocks):
        if not block.text_level or (block.bbox[3] - block.bbox[1]) < _MIN_HEADLINE_HEIGHT:
            continue
        text = block.text.strip()
        if not text or text.isdigit():
            continue
        if page_kinds.get(block.page_idx, PageKind("ad", "")).kind != "editorial":
            continue
        if text[:1] in _TITLE_SKIP_PREFIX:
            continue
        key = normalize_title(text)
        if key in section_names or key in _KNOWN_RUBRICS:
            continue
        if _is_pull_quote(block, paragraphs):
            continue
        candidates.append((index, block))

    # keep the topmost candidate per page (drops decks / sub-item / listicle headings)
    per_page: dict[int, tuple[int, Block]] = {}
    for index, block in candidates:
        current = per_page.get(block.page_idx)
        if current is None or block.bbox[1] < current[1].bbox[1]:
            per_page[block.page_idx] = (index, block)
    kept = sorted(per_page.values(), key=lambda item: item[0])

    # Join loop tracks heights in a parallel list (Boundary is a frozen dataclass,
    # so it must not carry an extra attribute).
    boundaries: list[Boundary] = []
    heights: list[int] = []
    for index, block in kept:
        title = _demirror(block.text.strip())
        height = block.bbox[3] - block.bbox[1]
        if boundaries:
            prev = boundaries[-1]
            same_or_next = 0 <= block.page_idx - prev.page_idx <= 1
            similar = abs(height - heights[-1]) < 40
            no_byline_between = not any(
                _is_byline(b) for b in blocks[prev.block_index + 1:index]
            )
            if same_or_next and similar and no_byline_between:
                boundaries[-1] = Boundary(
                    title=f"{prev.title} {title}",
                    page_idx=prev.page_idx,
                    block_index=prev.block_index,
                )
                continue
        boundaries.append(Boundary(title=title, page_idx=block.page_idx, block_index=index))
        heights.append(height)
    return boundaries
```

In `parse_bloomberg_edition`, change `boundaries = find_boundaries(blocks, contents, page_kinds)` to:

```python
    boundaries = find_boundaries(blocks, page_kinds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru.py -k find_boundaries -v`
Expected: PASS (both new tests).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "feat: heading-driven find_boundaries enumeration"
```

---

### Task 5: Remove dead code and fix the sanity warning

**Files:**
- Modify: `src/newspaper_translator/bloomberg_mineru.py` (remove `detect_page_offset`, `title_matches`, now-unused constants/imports; adjust `parse_bloomberg_edition`)
- Modify: `tests/test_bloomberg_mineru.py` (remove tests for deleted functions)
- Test: `tests/test_bloomberg_mineru.py`

**Interfaces:**
- Consumes: existing functions
- Produces: `parse_bloomberg_edition` no longer hard-fails on empty Contents; keeps the `< 0.6 * len(contents)` warning only when Contents is non-empty

After Task 4, `detect_page_offset`, `title_matches`, `_MIN_TITLE_HEIGHT`, `_MIN_OFFSET_VOTES`, and the `from collections import Counter` import are unused.

- [ ] **Step 1: Confirm they are unused**

Run: `grep -n "detect_page_offset\|title_matches\|_MIN_OFFSET_VOTES\|_MIN_TITLE_HEIGHT\|Counter" src/newspaper_translator/bloomberg_mineru.py`
Expected: matches only at their definitions/imports (no call sites). `normalize_title` remains used.

- [ ] **Step 2: Remove dead code**

Delete the `detect_page_offset` function, the `title_matches` function, the `_MIN_OFFSET_VOTES` and `_MIN_TITLE_HEIGHT` constants, and the `from collections import Counter` import. In `parse_bloomberg_edition`, replace the Contents hard-fail:

```python
    contents = parse_contents(blocks)
    if not contents:
        raise ValueError("Bloomberg Contents page not found in MinerU output")
    page_kinds = classify_pages(blocks)
```

with (Contents is now advisory only):

```python
    contents = parse_contents(blocks)
    page_kinds = classify_pages(blocks)
```

Keep the existing `if not articles: raise ValueError("Bloomberg parse produced no articles")`. Guard the warning so it only fires with a Contents baseline:

```python
    if contents and len(articles) < 0.6 * len(contents):
        debug_lines.insert(
            0,
            f"<!-- WARNING: {len(articles)} articles from "
            f"{len(contents)} Contents entries; MinerU may have missed titles -->",
        )
```

- [ ] **Step 3: Remove tests for deleted functions**

In `tests/test_bloomberg_mineru.py`, delete `test_detect_page_offset_votes`, `test_find_boundaries_folio_fallback_for_missed_title`, `test_find_boundaries_folio_fallback_distinct_indices_same_page`, `test_title_matches_containment_and_jaccard`, and any other test referencing `detect_page_offset` or `title_matches`. Keep `test_normalize_title_strips_punct_and_case`.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS, no `ImportError`, no reference to removed symbols.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_mineru.py tests/test_bloomberg_mineru.py
git commit -m "refactor: drop folio-fallback dead code; Contents advisory-only"
```

---

### Task 6: Opt-in real-issue regression test

**Files:**
- Create: `tests/test_bloomberg_mineru_headings_live.py`

**Interfaces:**
- Consumes: `load_content_list_from_dir`-style JSON loading, `load_blocks`, `classify_pages`, `find_boundaries`

Committing the full magazine JSON would embed copyrighted text, so this test is opt-in and reads a content_list path from an env var (like the existing `BLOOMBERG_LIVE_PDF` test).

- [ ] **Step 1: Write the test**

```python
# tests/test_bloomberg_mineru_headings_live.py
import json
import os
from pathlib import Path

import pytest

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
```

- [ ] **Step 2: Run it opt-in against the tuning fixture**

Run: `BLOOMBERG_CONTENT_LIST=tmp/bloomberg-fixture/june-2026-content_list.json .venv/bin/pytest tests/test_bloomberg_mineru_headings_live.py -v`
Expected: PASS (all 18 EXPECTED substrings present — the 19th, "The Summer of Our Discontent", is included; none of FORBIDDEN present).

- [ ] **Step 3: Confirm it skips without the env var**

Run: `.venv/bin/pytest tests/test_bloomberg_mineru_headings_live.py -v`
Expected: 1 skipped.

- [ ] **Step 4: Commit**

```bash
git add tests/test_bloomberg_mineru_headings_live.py
git commit -m "test: opt-in real-issue headline regression"
```

---

## Self-Review Notes

- **Spec coverage:** Rev2 "Corrected approach" bullets map to Task 2 (positive-signal classify), Tasks 3–4 (heading enumeration, exclusions, per-page topmost, split-join, de-mirror), Task 5 (Contents advisory-only). `assemble_articles` unchanged (Global Constraint). Known-limitation (Pursuits) is out of scope by design — the regression test asserts only the 19 front/feature headlines.
- **Type consistency:** `classify_pages(blocks)` and `find_boundaries(blocks, page_kinds)` new signatures are updated at their sole caller (`parse_bloomberg_edition`) in Tasks 2 and 4; `Boundary(title, page_idx, block_index)` unchanged; join loop avoids mutating the frozen dataclass (heights tracked in a parallel list).
- **Placeholder scan:** every code step contains complete code; the Task-4 join loop tracks heights in a parallel list to avoid mutating the frozen `Boundary`.
- **Fixture note:** the opt-in regression reads the gitignored `tmp/bloomberg-fixture/june-2026-content_list.json`; the full magazine JSON is never committed.
