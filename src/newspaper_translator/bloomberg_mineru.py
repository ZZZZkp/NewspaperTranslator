"""MinerU-driven Bloomberg Businessweek parser.

Replaces the local pypdf contents-folio parser. MinerU type:title blocks drive
article boundaries; the printed Contents page is an authoritative title
whitelist; ads are filtered at page granularity via the editorial fingerprint.
"""
import re
import shutil
import unicodedata
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



@dataclass(frozen=True)
class Boundary:
    title: str
    page_idx: int
    block_index: int


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


# Exclude A and I so standalone English words ("A dog", "I think") are not merged.
_DROPCAP_RE = re.compile(r"^([B-HJ-Z])\s+([a-z])")
_END_MARKER_RE = re.compile(r"\s*<BW>.*$", re.DOTALL)


def repair_dropcap(text: str) -> str:
    return _DROPCAP_RE.sub(r"\1\2", text)


def trim_end_marker(text: str) -> str:
    return _END_MARKER_RE.sub("", text).rstrip()


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
    page_kinds = classify_pages(blocks)
    boundaries = find_boundaries(blocks, page_kinds)
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
    if contents and len(articles) < 0.6 * len(contents):
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
