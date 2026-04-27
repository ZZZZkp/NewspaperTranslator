from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ArticleFragment:
    title: str
    body_text: str
    source_order: int
    continued_to_page: str
    continued_from_page: str


@dataclass(frozen=True)
class PageArticle:
    page_number: int
    x: float
    y_top: float
    title: str
    body_text: str


def extract_article_fragments_from_mineru_markdown(markdown_text: str) -> list[ArticleFragment]:
    fragments: list[ArticleFragment] = []
    current_title: str | None = None
    current_body_lines: list[str] = []

    def flush_current_article() -> None:
        nonlocal current_title, current_body_lines
        if not current_title or not current_body_lines:
            current_title = None
            current_body_lines = []
            return

        if _looks_like_mineru_teaser_body(current_body_lines):
            current_title = None
            current_body_lines = []
            return

        body_text = "\n".join(current_body_lines)
        fragments.append(
            ArticleFragment(
                title=current_title,
                body_text=body_text,
                source_order=len(fragments) + 1,
                continued_to_page=_extract_continued_to_page(body_text),
                continued_from_page=_extract_continued_from_page(body_text),
            )
        )
        current_title = None
        current_body_lines = []

    for raw_line in markdown_text.splitlines():
        normalized_line = raw_line.strip()
        if not normalized_line:
            continue

        if normalized_line.startswith("#"):
            heading = normalized_line.lstrip("#").strip()
            if not heading:
                continue

            if _looks_like_mineru_byline_heading(heading):
                if current_title is not None:
                    current_body_lines.append(heading)
                continue

            if _looks_like_mineru_heading_noise(heading):
                continue

            flush_current_article()
            current_title = heading
            current_body_lines = []
            continue

        if current_title is None:
            continue

        current_body_lines.append(normalized_line)

    flush_current_article()

    return fragments


def extract_articles_from_mineru_markdown(
    markdown_text: str,
    *,
    continuation_matcher=None,
) -> list[PageArticle]:
    fragments = extract_article_fragments_from_mineru_markdown(markdown_text)
    if continuation_matcher is not None:
        continuation_fragments = [
            fragment
            for fragment in fragments
            if fragment.continued_to_page or fragment.continued_from_page
        ]
        try:
            matches = continuation_matcher(continuation_fragments)
        except Exception:
            matches = []
        fragments = _merge_matched_fragments(
            fragments,
            matches=matches,
        )
    return [
        PageArticle(
            page_number=index,
            x=0.0,
            y_top=float(index),
            title=fragment.title,
            body_text=fragment.body_text,
        )
        for index, fragment in enumerate(fragments, start=1)
    ]


def parse_pdf_articles(
    path: Path,
    *,
    output_root: Path,
    mineru_client,
    continuation_matcher=None,
) -> list[PageArticle]:
    parsed_document = mineru_client.parse_pdf(pdf_path=Path(path), output_root=Path(output_root))
    return extract_articles_from_mineru_markdown(
        parsed_document.markdown_text,
        continuation_matcher=continuation_matcher,
    )


def _merge_matched_fragments(
    fragments: list[ArticleFragment],
    *,
    matches,
) -> list[ArticleFragment]:
    fragments_by_order = {fragment.source_order: fragment for fragment in fragments}
    merged_source_orders: set[int] = set()
    merged_fragments: list[ArticleFragment] = []

    for front_order, back_order in matches:
        front_fragment = fragments_by_order.get(front_order)
        back_fragment = fragments_by_order.get(back_order)
        if front_fragment is None or back_fragment is None:
            continue
        merged_source_orders.add(front_order)
        merged_source_orders.add(back_order)
        merged_fragments.append(
            ArticleFragment(
                title=front_fragment.title,
                body_text=_merge_fragment_body_text(front_fragment, back_fragment),
                source_order=front_fragment.source_order,
                continued_to_page=front_fragment.continued_to_page,
                continued_from_page=back_fragment.continued_from_page,
            )
        )

    for fragment in fragments:
        if fragment.source_order in merged_source_orders:
            continue
        merged_fragments.append(fragment)

    merged_fragments.sort(key=lambda fragment: fragment.source_order)
    return merged_fragments


def _extract_continued_to_page(body_text: str) -> str:
    match = re.search(r"please\s*turn\s*to\s*page\s*([A-Z]\d+)", body_text, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).upper()


def _extract_continued_from_page(body_text: str) -> str:
    match = re.search(
        r"continued\s*from\s*(PageOne|page\s*[A-Z]\d+)",
        body_text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    value = re.sub(r"\s+", "", match.group(1))
    if value.lower() == "pageone":
        return "PageOne"
    return value.removeprefix("page").removeprefix("Page")


def _merge_fragment_body_text(front_fragment: ArticleFragment, back_fragment: ArticleFragment) -> str:
    front_body = re.sub(
        r"\n?please\s*turn\s*to\s*page\s*[A-Z]\d+\s*$",
        "",
        front_fragment.body_text,
        flags=re.IGNORECASE,
    ).rstrip()
    back_body = re.sub(
        r"^continued\s*from\s*(?:PageOne|page\s*[A-Z]\d+)\s*",
        "",
        back_fragment.body_text,
        flags=re.IGNORECASE,
    ).lstrip()
    return f"{front_body}\n{back_body}"


def _looks_like_reference_marker(text: str) -> bool:
    normalized = text.strip()
    if len(normalized) not in {2, 3}:
        return False
    return normalized[0].isalpha() and normalized[1:].isdigit()


def _looks_like_mineru_byline_heading(text: str) -> bool:
    normalized = text.strip()
    return normalized.upper().startswith("BY ") and len(normalized) > 3


def _looks_like_mineru_heading_noise(text: str) -> bool:
    normalized = text.strip()
    lower = normalized.lower()
    if not normalized or not any(char.isalnum() for char in normalized):
        return True

    if lower in {
        "the wall street journal.",
        "what’s news",
        "business & finance",
        "worldwide",
        "journal report",
        "sports",
        "u.s. news",
        "u.s.watch",
        "iowa",
        "contents",
        "insid",
    }:
        return True

    return False


def _looks_like_mineru_teaser_body(body_lines: list[str]) -> bool:
    teaser_line_count = 0
    paragraph_like_line_count = 0
    section_label_count = 0
    short_page_ref_blurb_count = 0

    for line in body_lines:
        normalized = line.strip()
        if not normalized or normalized.startswith("![]("):
            continue

        if normalized.count(".") >= 8:
            teaser_line_count += 1
            continue

        if _looks_like_mineru_section_promo_label(normalized):
            section_label_count += 1
            continue

        if _looks_like_mineru_page_ref_blurb(normalized):
            short_page_ref_blurb_count += 1
            continue

        word_count = len(normalized.split())
        if word_count >= 8 or (word_count >= 6 and normalized[-1:] in {".", "!", "?"}):
            paragraph_like_line_count += 1

    if teaser_line_count >= 2 and paragraph_like_line_count == 0:
        return True

    return teaser_line_count >= 2 and section_label_count >= 2 and short_page_ref_blurb_count >= 2


def _looks_like_mineru_section_promo_label(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False

    alpha_count = sum(char.isalpha() for char in normalized)
    words = normalized.split()
    return alpha_count >= 3 and len(words) <= 3 and normalized.upper() == normalized


def _looks_like_mineru_page_ref_blurb(text: str) -> bool:
    normalized = text.strip()
    words = normalized.split()
    if len(words) < 4:
        return False

    last_token = words[-1].rstrip(".,;:")
    return _looks_like_reference_marker(last_token)
