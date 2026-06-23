"""Local parser for Bloomberg Businessweek PDFs (Contents-page driven).

Sibling to economist_edition.py. Routes Bloomberg PDFs away from MinerU by
deriving article boundaries from the printed Contents page plus a detected
printed-to-physical page-number offset. Reuses the generic edition structures.
"""
import re
import unicodedata
from collections import Counter
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
            index = clean_title.find(label + " ")
            if index != -1:
                section = label
                clean_title = clean_title[index + len(label):].strip()
                break
        entries.append(ContentsEntry(title=clean_title, section=section, folio=folio))
        last_folio = folio
    return entries


_FOLIO_HEADER_RE = re.compile(r"Bloomberg\s*Businessweek\s*(\d{1,3})")
_CONTENTS_SCAN_PAGES = 15
_MIN_CONTENTS_ENTRIES = 8
_MIN_OFFSET_VOTES = 2
_MAX_FOLIO_CAP = 999


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
        entries = parse_contents_entries(text, max_folio=max(total, _MAX_FOLIO_CAP))
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
