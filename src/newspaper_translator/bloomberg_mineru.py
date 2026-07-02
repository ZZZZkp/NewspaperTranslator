"""MinerU-driven Bloomberg Businessweek parser.

Replaces the local pypdf contents-folio parser. MinerU type:title blocks drive
article boundaries; the printed Contents page is an authoritative title
whitelist; ads are filtered at page granularity via the editorial fingerprint.
"""
import re
import shutil
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from newspaper_translator.economist_edition import (
    EditionArticle,
    ParsedEdition,
    build_economist_parse_result,
)
from pypdf import PdfReader


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
        used_indices = {b.block_index for b in bounds}
        for entry in contents:
            if normalize_title(entry.title) in matched_entries or entry.folio <= 0:
                continue
            target_page = entry.folio + offset - 1
            for index, block in enumerate(blocks):
                if (block.page_idx == target_page
                        and block.type in ("text", "paragraph")
                        and index not in used_indices
                        and page_kinds.get(block.page_idx, PageKind("ad", "")).kind
                        == "editorial"):
                    matched_entries.add(normalize_title(entry.title))
                    bounds.append(Boundary(entry.title, target_page, index))
                    used_indices.add(index)
                    break

    bounds.sort(key=lambda b: b.block_index)
    return bounds


# Exclude A and I so standalone English words ("A dog", "I think") are not merged.
_DROPCAP_RE = re.compile(r"^([B-HJ-Z])\s+([a-z])")
_END_MARKER_RE = re.compile(r"\s*<BW>.*$", re.DOTALL)


def repair_dropcap(text: str) -> str:
    return _DROPCAP_RE.sub(r"\1\2", text)


def trim_end_marker(text: str) -> str:
    return _END_MARKER_RE.sub("", text).rstrip()


def _copy_image(img_path: str, images_dir: Path, mineru_extract_dir: Path) -> str:
    # MinerU names extracted images by a sha256 content hash (e.g. images/<64-hex>.jpg).
    # Skipping copy when the destination basename already exists is therefore equivalent
    # to sha256 content-hash de-duplication, satisfying the Global Constraint.
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
    page_kinds = classify_pages(blocks)
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
