# Bloomberg Businessweek Contents-Page Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse Bloomberg Businessweek locally from its Contents page into ~35 TOC-aligned articles with hero images, replacing the MinerU over-fragmentation, and fall back to MinerU when the Contents page can't be parsed.

**Architecture:** A new `bloomberg_edition.py` (sibling to `economist_edition.py`) detects Bloomberg PDFs and parses them: it locates the Contents page, parses entries (`title … folio`), detects the printed→physical page offset by voting on `Bloomberg Businessweek <N>` headers, derives article page ranges, and extracts cleaned text plus embedded image references per range. A dedicated `persist_bloomberg_edition_articles` writes images under the output dir and reuses the existing parse-run persistence (which extracts `![](…)` refs into `article_images`, largest = hero). Routing adds a Bloomberg branch between Economist and MinerU. A parity fix makes `resolve_publication_date` resolve written-date filenames even when `issue_date` is NULL.

**Tech Stack:** Python 3.11+, `pypdf`, SQLite, `unittest`/`pytest`, existing parse-run + article-image persistence.

**Spec:** `docs/superpowers/specs/2026-06-23-bloomberg-contents-parser-design.md`

## Global Constraints

- `bloomberg_edition.py` depends only on `pypdf`, stdlib, and `economist_edition` (for the
  generic `EditionArticle` / `build_economist_parse_result` / `ParsedEdition`). No MinerU.
- Detection must be conservative: any unmet condition or `pypdf` read error → `False` →
  MinerU fallback. Never produce empty/broken Bloomberg output instead of falling back.
- `source_name = 彭博商业周刊` and `publication_date` come from the existing filename logic
  (`filename_metadata`); this plan does not re-derive them.
- Tests insert `src` onto `sys.path` themselves; run with `./.venv/bin/python -m pytest <path> -v`.
- v1 does NOT strip full-page ad pages; ad text is absorbed into the enclosing article.

---

## Task 1: Contents entry parsing

**Files:**
- Create: `src/newspaper_translator/bloomberg_edition.py`
- Test: `tests/test_bloomberg_edition.py`

**Interfaces:**
- Produces: `ContentsEntry(title: str, section: str, folio: int)` (frozen dataclass);
  `parse_contents_entries(text: str, *, max_folio: int) -> list[ContentsEntry]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bloomberg_edition.py`:

```python
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.bloomberg_edition import ContentsEntry, parse_contents_entries

# Real Contents-page lines from the sample issue (physical page 10).
SAMPLE_CONTENTS = "\n".join([
    " Bloomberg Businessweek8",
    "Contents Contributors",
    "Cover",
    "Remarks How will AI alter the economy? Ask a scarecrow 10",
    "In Context It’s a cruel summer for business owners everywhere 15",
    " Will the World Cup bring more drama on the ﬁeld or off? 19",
    " Seeking a better way to farm salmon 20",
    "In View Newer supporters to Trump: “We didn’t vote for this” 37",
    " Disposable labor powers the US workforce 40",
    "The AI Issue Constructing the global AI brain 43",
    " Andy Jassy on Amazon’s massive AI ambitions 44",
    "United’s CEO is fighting turf wars—and ",
    "courting\xa0influencers 84",
    "Pursuits It’s time to take back your time 93",
    "Exit Strategy What’s Chuck E. Cheese running from? 108",
    "How to contact Bloomberg Businessweek ⊿ Email bwreader@bloomberg.net ⊿ Ad sales 212 617-2900",
])


class ParseContentsEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = parse_contents_entries(SAMPLE_CONTENTS, max_folio=112)

    def test_folios_are_monotonic_and_in_range(self) -> None:
        folios = [e.folio for e in self.entries]
        self.assertEqual(folios, sorted(folios))
        self.assertTrue(all(1 <= f <= 112 for f in folios))

    def test_first_and_last_entries(self) -> None:
        self.assertEqual(self.entries[0].folio, 10)
        self.assertIn("How will AI alter the economy", self.entries[0].title)
        self.assertEqual(self.entries[-1].folio, 108)
        self.assertIn("Chuck E. Cheese", self.entries[-1].title)

    def test_wrapped_title_is_joined(self) -> None:
        wrapped = [e for e in self.entries if e.folio == 84]
        self.assertEqual(len(wrapped), 1)
        self.assertIn("United", wrapped[0].title)
        self.assertIn("courting", wrapped[0].title)

    def test_footer_phone_line_is_excluded(self) -> None:
        self.assertTrue(all("Ad sales" not in e.title for e in self.entries))
        self.assertTrue(all(e.folio != 212 for e in self.entries))

    def test_known_section_labels_are_split_off(self) -> None:
        remarks = [e for e in self.entries if e.folio == 10][0]
        self.assertEqual(remarks.section, "Remarks")
        self.assertNotIn("Remarks", remarks.title)
        # Carried forward to sub-entries until the next known label.
        farm = [e for e in self.entries if e.folio == 20][0]
        self.assertEqual(farm.section, "In Context")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newspaper_translator.bloomberg_edition'`

- [ ] **Step 3: Write minimal implementation**

Create `src/newspaper_translator/bloomberg_edition.py`:

```python
"""Local parser for Bloomberg Businessweek PDFs (Contents-page driven).

Sibling to economist_edition.py. Routes Bloomberg PDFs away from MinerU by
deriving article boundaries from the printed Contents page plus a detected
printed-to-physical page-number offset. Reuses the generic edition structures.
"""
import re
import unicodedata
from dataclasses import dataclass

_KNOWN_SECTIONS = ("Remarks", "In Context", "In View", "Pursuits", "Exit Strategy")
_TRAILING_FOLIO_RE = re.compile(r"^(?P<title>.*\S)\s+(?P<folio>\d{1,3})\s*$")


@dataclass(frozen=True)
class ContentsEntry:
    title: str
    section: str
    folio: int


def parse_contents_entries(text: str, *, max_folio: int) -> list[ContentsEntry]:
    raw: list[tuple[str, int]] = []
    pending: list[str] = []
    for raw_line in text.splitlines():
        line = unicodedata.normalize("NFKC", raw_line).strip()
        if not line:
            continue
        match = _TRAILING_FOLIO_RE.match(line)
        if match:
            title = " ".join([*pending, match.group("title")]).strip()
            raw.append((title, int(match.group("folio"))))
            pending = []
        else:
            pending.append(line)

    entries: list[ContentsEntry] = []
    section = ""
    last_folio = 0
    for title, folio in raw:
        if not (1 <= folio <= max_folio) or folio < last_folio:
            continue
        clean_title = title
        for label in _KNOWN_SECTIONS:
            if clean_title.startswith(label + " "):
                section = label
                clean_title = clean_title[len(label):].strip()
                break
        entries.append(ContentsEntry(title=clean_title, section=section, folio=folio))
        last_folio = folio
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
git commit -m "feat: parse Bloomberg Contents-page entries"
```

---

## Task 2: Contents page location and page-offset detection

**Files:**
- Modify: `src/newspaper_translator/bloomberg_edition.py`
- Test: `tests/test_bloomberg_edition.py`

**Interfaces:**
- Consumes: `parse_contents_entries` (Task 1).
- Produces: `find_contents_page(reader) -> int | None` (0-based index);
  `detect_page_offset(reader) -> int | None`. Both accept a `pypdf.PdfReader`.

- [ ] **Step 1: Write the failing test**

These need a `PdfReader`-like stub. Append to `tests/test_bloomberg_edition.py`:

```python
from newspaper_translator.bloomberg_edition import find_contents_page, detect_page_offset


class _StubPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _StubReader:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [_StubPage(t) for t in texts]


class FindContentsPageTests(unittest.TestCase):
    def test_finds_contents_page_index(self) -> None:
        # The Contents page must yield >= 8 entries to be accepted.
        listing = "\n".join(f"Item {i} title here {10 + i}" for i in range(8))
        reader = _StubReader([
            "cover art only",
            "masthead",
            "Contents Contributors\n" + listing,
        ])
        self.assertEqual(find_contents_page(reader), 2)

    def test_returns_none_when_no_contents(self) -> None:
        reader = _StubReader(["just a cover", "an article with prose and no listing"])
        self.assertIsNone(find_contents_page(reader))


class DetectPageOffsetTests(unittest.TestCase):
    def test_detects_constant_offset_by_vote(self) -> None:
        # physical index 7 (1-based 8) prints folio 6 -> offset +2, etc.
        texts = [""] * 12
        texts[7] = "Bloomberg Businessweek6\nbody"
        texts[9] = "Bloomberg Businessweek8\nbody"
        texts[17 % 12] = "noise"
        reader = _StubReader(texts)
        self.assertEqual(detect_page_offset(reader), 2)

    def test_returns_none_without_enough_markers(self) -> None:
        reader = _StubReader(["no folio here", "still none"])
        self.assertIsNone(detect_page_offset(reader))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::FindContentsPageTests tests/test_bloomberg_edition.py::DetectPageOffsetTests -v`
Expected: FAIL with `ImportError: cannot import name 'find_contents_page'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newspaper_translator/bloomberg_edition.py`:

```python
from collections import Counter

_FOLIO_HEADER_RE = re.compile(r"Bloomberg\s*Businessweek\s*(\d{1,3})")
_CONTENTS_SCAN_PAGES = 15
_MIN_CONTENTS_ENTRIES = 8
_MIN_OFFSET_VOTES = 5


def _page_text(reader, index: int) -> str:
    try:
        return reader.pages[index].extract_text() or ""
    except Exception:  # noqa: BLE001
        return ""


def find_contents_page(reader) -> int | None:
    total = len(reader.pages)
    for index in range(min(_CONTENTS_SCAN_PAGES, total)):
        text = _page_text(reader, index)
        if "Contents" not in text:
            continue
        entries = parse_contents_entries(text, max_folio=max(total, 1))
        if len(entries) >= _MIN_CONTENTS_ENTRIES:
            return index
    return None


def detect_page_offset(reader) -> int | None:
    votes: Counter[int] = Counter()
    for index in range(len(reader.pages)):
        match = _FOLIO_HEADER_RE.search(_page_text(reader, index))
        if match:
            printed = int(match.group(1))
            votes[(index + 1) - printed] += 1
    if not votes:
        return None
    offset, count = votes.most_common(1)[0]
    if count < _MIN_OFFSET_VOTES:
        return None
    return offset
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py -v`
Expected: PASS (all tests). The `FindContentsPageTests` stub already lists 8 entries, meeting
the `_MIN_CONTENTS_ENTRIES` gate.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
git commit -m "feat: locate Bloomberg Contents page and detect page offset"
```

---

## Task 3: Article page ranges

**Files:**
- Modify: `src/newspaper_translator/bloomberg_edition.py`
- Test: `tests/test_bloomberg_edition.py`

**Interfaces:**
- Consumes: `ContentsEntry` (Task 1).
- Produces: `BloombergArticleRange(title: str, section: str, start_page: int, end_page: int)`
  (1-based, `end_page` exclusive); `compute_article_ranges(entries, *, offset, total_pages)
  -> list[BloombergArticleRange]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bloomberg_edition.py`:

```python
from newspaper_translator.bloomberg_edition import (
    BloombergArticleRange,
    compute_article_ranges,
)


class ComputeArticleRangesTests(unittest.TestCase):
    def test_ranges_use_offset_and_span_to_next(self) -> None:
        entries = [
            ContentsEntry("A", "Remarks", 10),
            ContentsEntry("B", "In Context", 15),
            ContentsEntry("C", "Exit", 108),
        ]
        ranges = compute_article_ranges(entries, offset=2, total_pages=112)
        self.assertEqual(
            [(r.start_page, r.end_page) for r in ranges],
            [(12, 17), (17, 110), (110, 113)],
        )
        self.assertEqual(ranges[0].title, "A")

    def test_pages_before_first_entry_are_dropped(self) -> None:
        ranges = compute_article_ranges(
            [ContentsEntry("A", "", 10)], offset=2, total_pages=20
        )
        self.assertEqual(ranges[0].start_page, 12)  # pages 1..11 not covered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::ComputeArticleRangesTests -v`
Expected: FAIL with `ImportError: cannot import name 'BloombergArticleRange'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newspaper_translator/bloomberg_edition.py`:

```python
@dataclass(frozen=True)
class BloombergArticleRange:
    title: str
    section: str
    start_page: int  # 1-based, inclusive
    end_page: int  # 1-based, exclusive


def compute_article_ranges(
    entries: list[ContentsEntry], *, offset: int, total_pages: int
) -> list[BloombergArticleRange]:
    ordered = sorted(entries, key=lambda e: e.folio)
    starts = [e.folio + offset for e in ordered]
    ranges: list[BloombergArticleRange] = []
    for index, entry in enumerate(ordered):
        start = starts[index]
        end = starts[index + 1] if index + 1 < len(ordered) else total_pages + 1
        ranges.append(
            BloombergArticleRange(
                title=entry.title,
                section=entry.section,
                start_page=start,
                end_page=end,
            )
        )
    return ranges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::ComputeArticleRangesTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
git commit -m "feat: compute Bloomberg article page ranges from folios and offset"
```

---

## Task 4: Per-range text extraction and cleaning

**Files:**
- Modify: `src/newspaper_translator/bloomberg_edition.py`
- Test: `tests/test_bloomberg_edition.py`

**Interfaces:**
- Produces: `extract_article_text(reader, start_page: int, end_page: int) -> str` (cleans the
  running header and `ADVERTISEMENT` lines, collapses blank runs).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bloomberg_edition.py`:

```python
from newspaper_translator.bloomberg_edition import extract_article_text


class ExtractArticleTextTests(unittest.TestCase):
    def test_strips_header_and_ad_lines_and_joins_pages(self) -> None:
        reader = _StubReader([
            "x",
            "Bloomberg Businessweek44\nReal body line one.\nADVERTISEMENT\nMore body.",
            "Bloomberg Businessweek45\nSecond page body.",
        ])
        text = extract_article_text(reader, start_page=2, end_page=4)  # 1-based pages 2,3
        self.assertIn("Real body line one.", text)
        self.assertIn("Second page body.", text)
        self.assertNotIn("Bloomberg Businessweek", text)
        self.assertNotIn("ADVERTISEMENT", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::ExtractArticleTextTests -v`
Expected: FAIL with `ImportError: cannot import name 'extract_article_text'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newspaper_translator/bloomberg_edition.py`:

```python
_AD_LINE_RE = re.compile(r"^\s*ADVERTISEMENT\s*$", re.IGNORECASE)


def extract_article_text(reader, start_page: int, end_page: int) -> str:
    parts: list[str] = []
    for page_number in range(start_page, end_page):
        parts.append(_page_text(reader, page_number - 1))
    raw = "\n".join(parts)
    cleaned_lines: list[str] = []
    for raw_line in raw.splitlines():
        line = _FOLIO_HEADER_RE.sub("", raw_line).rstrip()
        if _AD_LINE_RE.match(line):
            continue
        cleaned_lines.append(line)
    body = "\n".join(cleaned_lines).strip()
    return re.sub(r"\n{3,}", "\n\n", body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::ExtractArticleTextTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
git commit -m "feat: extract and clean Bloomberg article text per page range"
```

---

## Task 5: Per-range image extraction and reference embedding

**Files:**
- Modify: `src/newspaper_translator/bloomberg_edition.py`
- Test: `tests/test_bloomberg_edition.py`

**Interfaces:**
- Produces: `extract_article_images(reader, start_page, end_page, images_dir: Path) ->
  list[str]` — writes each embedded image to `images_dir` named by content hash, returns the
  list of `images/<name>` POSIX-relative paths (relative to `images_dir.parent`) to embed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bloomberg_edition.py`:

```python
import hashlib
import tempfile
from newspaper_translator.bloomberg_edition import extract_article_images


class _StubImage:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self.data = data


class _StubImagePage:
    def __init__(self, images: list) -> None:
        self.images = images

    def extract_text(self) -> str:
        return ""


class _StubImageReader:
    def __init__(self, pages_images: list[list]) -> None:
        self.pages = [_StubImagePage(imgs) for imgs in pages_images]


class ExtractArticleImagesTests(unittest.TestCase):
    def test_writes_images_and_returns_relative_refs(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"abc"
        jpg = b"\xff\xd8\xff" + b"def"
        reader = _StubImageReader([[], [_StubImage("a.png", png)], [_StubImage("b.jpg", jpg)]])
        with tempfile.TemporaryDirectory() as tmp:
            images_dir = pathlib.Path(tmp) / "stem" / "images"
            refs = extract_article_images(reader, 2, 4, images_dir)  # pages 2,3
            self.assertEqual(len(refs), 2)
            self.assertTrue(all(r.startswith("images/") for r in refs))
            for r in refs:
                self.assertTrue((images_dir.parent / r).exists())

    def test_returns_empty_when_no_images(self) -> None:
        reader = _StubImageReader([[], []])
        with tempfile.TemporaryDirectory() as tmp:
            images_dir = pathlib.Path(tmp) / "stem" / "images"
            self.assertEqual(extract_article_images(reader, 1, 3, images_dir), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::ExtractArticleImagesTests -v`
Expected: FAIL with `ImportError: cannot import name 'extract_article_images'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newspaper_translator/bloomberg_edition.py` (add `import hashlib` and
`from pathlib import Path` at the top):

```python
def extract_article_images(reader, start_page: int, end_page: int, images_dir: Path) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for page_number in range(start_page, end_page):
        try:
            images = reader.pages[page_number - 1].images
        except Exception:  # noqa: BLE001
            continue
        for image in images:
            try:
                data = image.data
            except Exception:  # noqa: BLE001
                continue
            if not data:
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            suffix = Path(getattr(image, "name", "") or "").suffix.lower() or ".jpg"
            if suffix not in {".jpg", ".jpeg", ".png"}:
                suffix = ".jpg"
            images_dir.mkdir(parents=True, exist_ok=True)
            file_path = images_dir / f"{digest}{suffix}"
            if not file_path.exists():
                file_path.write_bytes(data)
            refs.append(f"images/{file_path.name}")
    return refs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::ExtractArticleImagesTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
git commit -m "feat: extract Bloomberg article images and embed relative refs"
```

---

## Task 6: Assemble parser and detection

**Files:**
- Modify: `src/newspaper_translator/bloomberg_edition.py`
- Test: `tests/test_bloomberg_edition.py`

**Interfaces:**
- Consumes: all helpers above; `EditionArticle`, `build_economist_parse_result`,
  `ParsedEdition` from `economist_edition`.
- Produces: `BLOOMBERG_EDITION_PARSER_VERSION = "bloomberg-edition-v1"`;
  `parse_bloomberg_edition(pdf_path, *, images_dir: Path) -> ParsedEdition`;
  `detect_bloomberg_edition(pdf_path) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bloomberg_edition.py`:

```python
from newspaper_translator.bloomberg_edition import (
    BLOOMBERG_EDITION_PARSER_VERSION,
    detect_bloomberg_edition,
)


class DetectBloombergEditionTests(unittest.TestCase):
    def test_real_sample_detected(self) -> None:
        sample = "/Users/pzk/workspace/NewspaperTranslator/Bloomberg Businessweek USA - June 2026.pdf"
        if not pathlib.Path(sample).exists():
            self.skipTest("sample PDF not present")
        self.assertTrue(detect_bloomberg_edition(sample))

    def test_missing_file_returns_false(self) -> None:
        self.assertFalse(detect_bloomberg_edition("/nonexistent/file.pdf"))

    def test_parser_version_constant(self) -> None:
        self.assertEqual(BLOOMBERG_EDITION_PARSER_VERSION, "bloomberg-edition-v1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py::DetectBloombergEditionTests -v`
Expected: FAIL with `ImportError: cannot import name 'BLOOMBERG_EDITION_PARSER_VERSION'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newspaper_translator/bloomberg_edition.py` (add `from pypdf import PdfReader` and
the economist imports at the top):

```python
from pypdf import PdfReader

from newspaper_translator.economist_edition import (
    EditionArticle,
    ParsedEdition,
    build_economist_parse_result,
)

BLOOMBERG_EDITION_PARSER_VERSION = "bloomberg-edition-v1"


def detect_bloomberg_edition(pdf_path) -> bool:
    try:
        reader = PdfReader(str(pdf_path))
        producer = str((reader.metadata or {}).get("/Producer") or "").lower()
        sample = "".join(
            _page_text(reader, i) for i in range(min(_CONTENTS_SCAN_PAGES, len(reader.pages)))
        )
        if "bloomberg businessweek" not in sample.lower():
            return False
        if "calibre" in producer:
            return False
        if find_contents_page(reader) is None:
            return False
        if detect_page_offset(reader) is None:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def parse_bloomberg_edition(pdf_path, *, images_dir: Path) -> ParsedEdition:
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    contents_index = find_contents_page(reader)
    offset = detect_page_offset(reader)
    if contents_index is None or offset is None:
        raise ValueError("Bloomberg Contents page or page offset not found")

    entries = parse_contents_entries(
        _page_text(reader, contents_index), max_folio=total_pages
    )
    ranges = compute_article_ranges(entries, offset=offset, total_pages=total_pages)

    articles: list[EditionArticle] = []
    debug_parts: list[str] = []
    for article_range in ranges:
        body_text = extract_article_text(reader, article_range.start_page, article_range.end_page)
        image_refs = extract_article_images(
            reader, article_range.start_page, article_range.end_page, images_dir
        )
        if not body_text.strip() and not image_refs:
            continue
        body_with_images = body_text
        if image_refs:
            body_with_images = body_text + "\n\n" + "\n".join(f"![]({ref})" for ref in image_refs)
        articles.append(
            EditionArticle(
                title=article_range.title,
                section=article_range.section,
                start_page=article_range.start_page,
                end_page=article_range.end_page,
                body_text=body_with_images,
                url="",
            )
        )
        debug_parts.append(
            f"<!-- ARTICLE: {article_range.title} | section={article_range.section} "
            f"| pages={article_range.start_page}-{article_range.end_page - 1} "
            f"| images={len(image_refs)} -->\n{body_text}\n"
        )

    return ParsedEdition(
        parse_result=build_economist_parse_result(articles),
        debug_text="\n".join(debug_parts),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_bloomberg_edition.py -v`
Expected: PASS (the real-sample detection test passes if the sample PDF is present, else skips).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/bloomberg_edition.py tests/test_bloomberg_edition.py
git commit -m "feat: assemble Bloomberg edition parser and detection"
```

---

## Task 7: Persistence and routing

**Files:**
- Modify: `src/newspaper_translator/article_pipeline.py`
- Modify: `src/newspaper_translator/document_processing.py:1886-1908`
- Test: `tests/test_document_processing_economist_routing.py`

**Interfaces:**
- Consumes: `parse_bloomberg_edition`, `detect_bloomberg_edition`,
  `BLOOMBERG_EDITION_PARSER_VERSION`.
- Produces: `persist_bloomberg_edition_articles(*, database_url, document_key, output_root)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_document_processing_economist_routing.py` a routing test:

```python
    def test_routes_bloomberg_to_local_persist(self) -> None:
        document = document_processing.StoredDocument(
            document_key="doc-key",
            original_filename="Bloomberg Businessweek USA - June 2026.pdf",
            raw_path="/tmp/bbw.pdf",
            source_message_internal_date=None,
        )
        callback = document_processing._build_parse_persist_callback(
            database_url="sqlite:////tmp/does-not-matter.db",
            output_root="/tmp/out",
            mineru_client=_StubMineru(),
            continuation_matcher=None,
            parser_name="mineru",
            parser_version="vlm",
            continuation_matcher_name="deepseek",
            continuation_matcher_version="deepseek-chat",
        )
        with patch.object(document_processing, "_get_document", return_value=document), \
             patch.object(document_processing, "detect_calibre_economist_edition", return_value=False), \
             patch.object(document_processing, "detect_bloomberg_edition", return_value=True) as detect, \
             patch.object(document_processing, "persist_bloomberg_edition_articles") as bbw_persist, \
             patch.object(document_processing, "persist_document_articles") as mineru_persist:
            callback(document_key="doc-key")
        detect.assert_called_once()
        bbw_persist.assert_called_once()
        mineru_persist.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_document_processing_economist_routing.py::EconomistRoutingTests::test_routes_bloomberg_to_local_persist -v`
Expected: FAIL with `AttributeError: ... does not have the attribute 'detect_bloomberg_edition'`

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/article_pipeline.py`, add after `persist_economist_edition_articles`
(reusing its structure but threading an images dir and the Bloomberg parser):

```python
from newspaper_translator.bloomberg_edition import (
    BLOOMBERG_EDITION_PARSER_VERSION,
    parse_bloomberg_edition,
)


def persist_bloomberg_edition_articles(
    *,
    database_url: str,
    document_key: str,
    output_root: Path,
    parser_name: str = "bloomberg-edition",
    parser_version: str = BLOOMBERG_EDITION_PARSER_VERSION,
):
    document = _get_document(database_url=database_url, document_key=document_key)

    debug_dir = Path(output_root) / Path(document.raw_path).stem
    images_dir = debug_dir / "images"
    debug_dir.mkdir(parents=True, exist_ok=True)
    parsed_edition = parse_bloomberg_edition(Path(document.raw_path), images_dir=images_dir)

    debug_path = debug_dir / "full-edition.txt"
    debug_path.write_text(parsed_edition.debug_text, encoding="utf-8")

    publication_date = resolve_publication_date(
        original_filename=document.original_filename,
        markdown_text=parsed_edition.debug_text,
        source_message_internal_date=document.source_message_internal_date,
        fallback_year=datetime.now().year,
        issue_date=document.issue_date,
    )

    parse_run = create_parse_run(
        database_url=database_url,
        document_key=document_key,
        parser_name=parser_name,
        parser_version=parser_version,
        publication_date=publication_date or "",
        continuation_matcher_name="",
        continuation_matcher_version="",
    )
    update_parse_run_source_artifacts(
        database_url=database_url,
        parse_run_id=parse_run.parse_run_id,
        mineru_batch_id="",
        mineru_file_id="bloomberg-edition",
        markdown_path=str(debug_path),
    )

    if not publication_date:
        error_message = (
            "Unable to resolve publication date for Bloomberg edition from filename or content"
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="failed",
            error_message=error_message,
        )
        raise ValueError(error_message)

    record_parse_run_result(
        database_url=database_url,
        parse_run_id=parse_run.parse_run_id,
        parse_result=parsed_edition.parse_result,
        document_key=document_key,
        publication_date=publication_date,
    )
    finalize_parse_run(
        database_url=database_url,
        parse_run_id=parse_run.parse_run_id,
        status="succeeded",
    )
```

In `src/newspaper_translator/document_processing.py`, import the new symbols near the
economist imports (around line 13-17):

```python
from newspaper_translator.article_pipeline import (
    ...,
    persist_bloomberg_edition_articles,
)
from newspaper_translator.bloomberg_edition import detect_bloomberg_edition
```

Then in `_build_parse_persist_callback`'s `_callback` (currently around lines 1886-1908),
add the Bloomberg branch between the Economist branch and the MinerU call:

```python
    def _callback(*, document_key: str) -> None:
        document = _get_document(database_url=database_url, document_key=document_key)
        if detect_calibre_economist_edition(Path(document.raw_path)):
            persist_economist_edition_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=Path(output_root),
                parser_name="economist-edition",
                parser_version=ECONOMIST_EDITION_PARSER_VERSION,
            )
            return
        if detect_bloomberg_edition(Path(document.raw_path)):
            persist_bloomberg_edition_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=Path(output_root),
            )
            return
        persist_document_articles(
            database_url=database_url,
            document_key=document_key,
            output_root=Path(output_root),
            mineru_client=mineru_client,
            continuation_matcher=continuation_matcher,
            parser_name=parser_name,
            parser_version=parser_version,
            continuation_matcher_name=continuation_matcher_name,
            continuation_matcher_version=continuation_matcher_version,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_document_processing_economist_routing.py -v`
Expected: PASS (both the new Bloomberg test and the existing Economist/MinerU routing tests).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/article_pipeline.py src/newspaper_translator/document_processing.py tests/test_document_processing_economist_routing.py
git commit -m "feat: persist Bloomberg edition articles and route to local parser"
```

---

## Task 8: Publication-date parity fix

**Files:**
- Modify: `src/newspaper_translator/article_pipeline.py:198-219`
- Test: `tests/test_resolve_publication_date.py`

**Interfaces:**
- Consumes: `filename_metadata.extract_filename_date`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_resolve_publication_date.py`:

```python
    def test_written_month_year_filename_without_issue_date(self) -> None:
        # issue_date NULL (e.g. reprocessing an old row); must not fall back to markdown.
        self.assertEqual(
            resolve_publication_date(
                original_filename="Bloomberg Businessweek USA - June 2026.pdf",
                markdown_text="March 30, 1979 was a date",
                issue_date=None,
            ),
            "2026-06-01",
        )

    def test_written_day_month_year_filename_without_issue_date(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="The Economist USA - June 20 2026.pdf",
                markdown_text="January 1, 2000",
                issue_date=None,
            ),
            "2026-06-20",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_resolve_publication_date.py -v`
Expected: FAIL — both return the markdown date (`1979-03-30` / `2000-01-01`) instead of the
filename date.

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/article_pipeline.py`, add the import near the top:

```python
from newspaper_translator.filename_metadata import extract_filename_date
```

Replace the body of `resolve_publication_date` (keep the signature) so the filename resolver
(which covers ISO, `M-D` with Gmail-year completion, `Month D YYYY`, and `Month YYYY`) is the
single filename step before markdown fallback:

```python
def resolve_publication_date(
    *,
    original_filename: str,
    markdown_text: str,
    source_message_internal_date: str | None = None,
    fallback_year: int | None = None,
    issue_date: str | None = None,
) -> str:
    if issue_date:
        _log_publication_date_resolution(
            event="publication_date_resolved",
            details={
                "original_filename": original_filename,
                "resolution_source": "stored_issue_date",
                "publication_date": issue_date,
            },
        )
        return issue_date

    filename_date = extract_filename_date(
        original_filename,
        source_message_internal_date=source_message_internal_date,
        fallback_year=fallback_year or datetime.now().year,
    )
    if filename_date:
        _log_publication_date_resolution(
            event="publication_date_resolved",
            details={
                "original_filename": original_filename,
                "resolution_source": "filename",
                "publication_date": filename_date,
            },
        )
        return filename_date

    return _extract_written_date_from_text(markdown_text) or _extract_iso_date_from_text(
        markdown_text
    )
```

Note: `_extract_iso_date_from_text` and `_extract_month_day_date_from_filename` may now be
unused by this function. Leave `_extract_iso_date_from_text` (still used for the markdown
fallback). If `_extract_month_day_date_from_filename` becomes unused, remove it to avoid dead
code; if other code references it, leave it.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_resolve_publication_date.py tests/test_process_document.py tests/test_economist_edition_pipeline.py -v`
Expected: PASS (new tests plus all existing date-resolution tests — confirm `M-D` filename
and markdown-fallback cases still pass).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/article_pipeline.py tests/test_resolve_publication_date.py
git commit -m "fix: resolve written-date filenames before markdown fallback"
```

---

## Task 9: Full suite, real-sample smoke, and re-import remediation

**Files:** none (verification + operational remediation)

- [ ] **Step 1: Run the full test suite**

Run: `./.venv/bin/python -m pytest tests/ -q`
Expected: all tests pass. Fix any regression before continuing.

- [ ] **Step 2: Real-sample smoke (local, no DB)**

```bash
PYTHONPATH=src ./.venv/bin/python - <<'PY'
from pathlib import Path
import tempfile
from newspaper_translator.bloomberg_edition import detect_bloomberg_edition, parse_bloomberg_edition
sample = "/Users/pzk/workspace/NewspaperTranslator/Bloomberg Businessweek USA - June 2026.pdf"
print("detected:", detect_bloomberg_edition(sample))
with tempfile.TemporaryDirectory() as tmp:
    edition = parse_bloomberg_edition(Path(sample), images_dir=Path(tmp) / "images")
    arts = edition.parse_result.articles
    print("article count:", len(arts))
    imgs = sum(1 for d in edition.debug_text.splitlines() if "images=" in d)
    print("debug article markers:", imgs)
PY
```
Expected: `detected: True`; `article count` roughly the Contents-entry count (~30-40), NOT
~141. If the count is ~141 or detection is False, STOP and investigate before remediation.

- [ ] **Step 3: Deploy the branch to the containers**

The running containers are on old `main` (no `filename_metadata.py`, migrations stop at
0014). Rebuild and restart so the new code and migration `0015` are live:

```bash
docker compose up -d --build worker article-worker web
docker compose exec -T worker sh -c 'ls src/newspaper_translator/bloomberg_edition.py && ls src/newspaper_translator/migrations | tail -2'
```
Expected: `bloomberg_edition.py` present and `0015_documents_issue_date.sql` listed. Migrations
run on startup; confirm `issue_date` column exists:
```bash
docker compose exec -T worker python -c "import sqlite3;print('issue_date' in [r[1] for r in sqlite3.connect('/data/newspaper-translator.db').execute('PRAGMA table_info(documents)')])"
```
Expected: `True`.

- [ ] **Step 4: Re-import Bloomberg and Economist USA**

Delete the wrongly-imported Bloomberg and Economist-USA documents and re-import so the new
code writes correct `source_name` / `issue_date` and re-parses with the new routes. Identify
the documents and remove their `documents` + dependent rows, then trigger a fresh import via
the existing manual import path.

```bash
# Identify the affected documents (wrong source_name = raw filename stem).
docker compose exec -T worker python - <<'PY'
import sqlite3
c=sqlite3.connect("/data/newspaper-translator.db")
for r in c.execute("SELECT document_key, source_name, original_filename FROM documents WHERE original_filename LIKE 'Bloomberg%' OR original_filename LIKE 'The Economist USA%'").fetchall():
    print(r)
PY
```

Re-import: trigger the manual Gmail import (the same email source) so the unchanged PDFs are
re-fetched. With the deployed branch, the issue-identity dedupe keys on
`(source_name, issue_date)`; because the OLD rows have the wrong `source_name` and NULL
`issue_date`, a fresh import will NOT dedupe against them and will create correct canonical
rows. Then remove the stale wrong rows so only the corrected documents remain. Use the
operator workbench "fetch latest mail" button or:
```bash
docker compose exec -T worker python -m newspaper_translator.manage gmail-import
```
Confirm the corrected rows:
```bash
docker compose exec -T worker python - <<'PY'
import sqlite3
c=sqlite3.connect("/data/newspaper-translator.db")
for r in c.execute("SELECT source_name, issue_date, original_filename FROM documents WHERE original_filename LIKE 'Bloomberg%' OR original_filename LIKE 'The Economist USA%' ORDER BY rowid DESC").fetchall():
    print(r)
PY
```
Expected new rows: `('彭博商业周刊','2026-06-01',...)` and `('经济学人','2026-06-20',...)`.

**This step is operational and touches production data; confirm with the user before deleting
any rows.** Removing stale documents and their parse/enrichment history is destructive — list
exactly what will be deleted and get explicit approval first.

- [ ] **Step 5: Verify end state**

After re-processing completes, confirm in the workbench/dashboard: Bloomberg shows
`彭博商业周刊`, date `2026-06-01`, ~35 article cards (not 141) with hero images; Economist USA
shows `经济学人`, date `2026-06-20`.

---

## Self-Review Notes

- **Spec coverage:** Contents detection/parsing (Tasks 1-2), offset + ranges (Tasks 2-3),
  text + image extraction (Tasks 4-5), parser assembly + detection + fallback (Task 6),
  persistence + routing reusing the article-image flow (Task 7), publication-date parity fix
  + dual Economist format (Task 8), full suite + real-sample smoke + deploy/re-import
  remediation (Task 9).
- **Image flow:** `parse_bloomberg_edition` embeds `![](images/<hash>.jpg)` refs; the persist
  sets `markdown_path` under `output_root/<stem>/` so `record_parse_run_result` resolves them
  against that dir into `article_images` (largest = hero) — no new image storage code.
- **Fallback:** `detect_bloomberg_edition` returns False on any unmet condition or read error
  → MinerU; the Economist Calibre branch runs first and is unaffected.
- **Type consistency:** `ContentsEntry`, `BloombergArticleRange`, `parse_bloomberg_edition(…,
  images_dir=…)`, `detect_bloomberg_edition`, `BLOOMBERG_EDITION_PARSER_VERSION`,
  `persist_bloomberg_edition_articles` are used consistently across Tasks 1-7.
