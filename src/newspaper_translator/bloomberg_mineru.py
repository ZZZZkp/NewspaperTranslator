"""MinerU-driven Bloomberg Businessweek parser.

Replaces the local pypdf contents-folio parser. MinerU type:title blocks drive
article boundaries; the printed Contents page is an authoritative title
whitelist; ads are filtered at page granularity via the editorial fingerprint.
"""
import re
import unicodedata
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
