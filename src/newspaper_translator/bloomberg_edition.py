"""Local parser for Bloomberg Businessweek PDFs (Contents-page driven).

Sibling to economist_edition.py. Routes Bloomberg PDFs away from MinerU by
deriving article boundaries from the printed Contents page plus a detected
printed-to-physical page-number offset. Reuses the generic edition structures.
"""
import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from newspaper_translator.economist_edition import (
    EditionArticle,
    ParsedEdition,
    build_economist_parse_result,
)

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
_MIN_OFFSET_VOTES = 3
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
