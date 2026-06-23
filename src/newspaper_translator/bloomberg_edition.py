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
            index = clean_title.find(label + " ")
            if index != -1:
                section = label
                clean_title = clean_title[index + len(label):].strip()
                break
        entries.append(ContentsEntry(title=clean_title, section=section, folio=folio))
        last_folio = folio
    return entries
