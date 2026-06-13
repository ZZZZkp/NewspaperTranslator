import re
from dataclasses import dataclass


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
