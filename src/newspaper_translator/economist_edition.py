import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from newspaper_translator.pdf import (
    ArticleFragment,
    ArticleSource,
    ParsedArticle,
    ParseResult,
)


@dataclass(frozen=True)
class OutlineEntry:
    title: str
    section: str
    start_page: int  # 1-based
    is_leaf: bool


@dataclass(frozen=True)
class ArticleRange:
    title: str
    section: str
    start_page: int
    end_page: int  # exclusive, 1-based


def compute_article_ranges(
    entries: list[OutlineEntry],
    *,
    total_pages: int,
) -> list[ArticleRange]:
    boundaries = sorted({entry.start_page for entry in entries})
    ranges: list[ArticleRange] = []
    for entry in entries:
        if not entry.is_leaf:
            continue
        end_page = next(
            (boundary for boundary in boundaries if boundary > entry.start_page),
            total_pages + 1,
        )
        ranges.append(
            ArticleRange(
                title=entry.title,
                section=entry.section,
                start_page=entry.start_page,
                end_page=end_page,
            )
        )
    ranges.sort(key=lambda article_range: article_range.start_page)
    return ranges


_NAV_TOKENS = ("下一项", "上一项", "章节菜单", "主菜单")
_CALIBRE_URL_MARKER = "downloaded by calibre from"
_SUBSCRIBER_PROMO = re.compile(
    r"Subscribers to The Economist can sign up",
    re.IGNORECASE,
)
_TIMESTAMP_LINE = re.compile(
    r"^\d{1,2}\s*[月⽉]\s*\d{1,2},?\s*\d{4}\s+\d{1,2}:\d{2}\s*(上午|下午)$"
)


def clean_edition_text(raw: str) -> tuple[str, str]:
    url = _extract_calibre_url(raw)

    text = raw
    marker_index = text.lower().find(_CALIBRE_URL_MARKER)
    if marker_index != -1:
        text = text[:marker_index]
    promo_match = _SUBSCRIBER_PROMO.search(text)
    if promo_match:
        text = text[: promo_match.start()]

    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.replace("■", "").rstrip()
        stripped = line.strip()
        if _is_nav_line(stripped):
            continue
        if _TIMESTAMP_LINE.match(stripped):
            continue
        cleaned_lines.append(line)

    body = "\n".join(cleaned_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body, url


def _is_nav_line(text: str) -> bool:
    if not text or not any(token in text for token in _NAV_TOKENS):
        return False
    residue = text
    for token in _NAV_TOKENS:
        residue = residue.replace(token, "")
    residue = residue.replace("|", "").strip()
    return residue == ""


def _extract_calibre_url(raw: str) -> str:
    match = re.search(
        rf"{_CALIBRE_URL_MARKER}\s*(.+)",
        raw,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    chunk_lines: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            if chunk_lines:
                break
            continue
        if _is_nav_line(stripped):
            break
        chunk_lines.append(stripped)
    joined = "".join(chunk_lines)  # rejoins URLs split across wrapped lines
    url_match = re.search(r"https?://\S+", joined)
    return url_match.group(0) if url_match else ""


@dataclass(frozen=True)
class EditionArticle:
    title: str
    section: str
    start_page: int
    end_page: int
    body_text: str
    url: str


def build_economist_parse_result(articles: list[EditionArticle]) -> ParseResult:
    fragments: list[ArticleFragment] = []
    parsed_articles: list[ParsedArticle] = []
    for index, article in enumerate(articles, start=1):
        fragments.append(
            ArticleFragment(
                title=article.title,
                body_text=article.body_text,
                source_order=index,
                continued_to_page="",
                continued_from_page="",
                page_number=article.start_page,
            )
        )
        parsed_articles.append(
            ParsedArticle(
                article_order=index,
                primary_source_order=index,
                source_fragment_count=1,
                title=article.title,
                body_text=article.body_text,
                source_fragments=[
                    ArticleSource(
                        source_order=index,
                        fragment_role="standalone",
                        sequence_index=1,
                    )
                ],
            )
        )
    return ParseResult(
        fragments=fragments,
        match_decisions=[],
        articles=parsed_articles,
    )


ECONOMIST_EDITION_PARSER_VERSION = "economist-edition-v1"


@dataclass(frozen=True)
class ParsedEdition:
    parse_result: ParseResult
    debug_text: str


def extract_outline_entries(reader) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []

    def page_of(dest) -> int | None:
        try:
            return reader.get_destination_page_number(dest) + 1
        except Exception:  # noqa: BLE001
            return None

    def walk(items, section: str) -> None:
        index = 0
        while index < len(items):
            item = items[index]
            if isinstance(item, list):
                walk(item, section)
                index += 1
                continue
            children = (
                items[index + 1]
                if index + 1 < len(items) and isinstance(items[index + 1], list)
                else None
            )
            title = (getattr(item, "title", "") or "").strip()
            start_page = page_of(item)
            if children is not None:
                if start_page is not None:
                    entries.append(
                        OutlineEntry(
                            title=title,
                            section=section,
                            start_page=start_page,
                            is_leaf=False,
                        )
                    )
                walk(children, title or section)
                index += 2
            else:
                if start_page is not None:
                    entries.append(
                        OutlineEntry(
                            title=title,
                            section=section,
                            start_page=start_page,
                            is_leaf=True,
                        )
                    )
                index += 1

    walk(reader.outline or [], "")
    return entries


def extract_article_text(reader, start_page: int, end_page: int) -> tuple[str, str]:
    parts: list[str] = []
    for page_number in range(start_page, end_page):
        page = reader.pages[page_number - 1]
        parts.append(page.extract_text() or "")
    return clean_edition_text("\n".join(parts))


def detect_calibre_economist_edition(pdf_path) -> bool:
    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata or {}
        producer = str(metadata.get("/Producer") or "")
        if "calibre" not in producer.lower():
            return False
        entries = extract_outline_entries(reader)
        leaf_count = sum(1 for entry in entries if entry.is_leaf)
        if leaf_count < 3:
            return False
        title = str(metadata.get("/Title") or "")
        if "economist" in title.lower():
            return True
        sample = "".join(
            (reader.pages[index].extract_text() or "")
            for index in range(min(8, len(reader.pages)))
        )
        return "economist.com" in sample.lower()
    except Exception:  # noqa: BLE001
        return False


def parse_economist_edition(pdf_path) -> ParsedEdition:
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    entries = extract_outline_entries(reader)
    ranges = compute_article_ranges(entries, total_pages=total_pages)

    articles: list[EditionArticle] = []
    debug_parts: list[str] = []
    for article_range in ranges:
        body_text, url = extract_article_text(
            reader,
            article_range.start_page,
            article_range.end_page,
        )
        if not body_text.strip():
            continue
        articles.append(
            EditionArticle(
                title=article_range.title,
                section=article_range.section,
                start_page=article_range.start_page,
                end_page=article_range.end_page,
                body_text=body_text,
                url=url,
            )
        )
        debug_parts.append(
            f"<!-- ARTICLE: {article_range.title} | section={article_range.section} "
            f"| pages={article_range.start_page}-{article_range.end_page - 1} | url={url} -->\n"
            f"{body_text}\n"
        )

    return ParsedEdition(
        parse_result=build_economist_parse_result(articles),
        debug_text="\n".join(debug_parts),
    )
