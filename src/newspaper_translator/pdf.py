from dataclasses import dataclass
from pathlib import Path
import re

from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class ArticleFragment:
    title: str
    body_text: str
    source_order: int
    continued_to_page: str
    continued_from_page: str
    page_number: int = 0


@dataclass(frozen=True)
class ParsedMarkdownPage:
    page_number: int
    markdown_text: str


@dataclass(frozen=True)
class SinglePagePdf:
    page_number: int
    path: Path


@dataclass(frozen=True)
class PageArticle:
    page_number: int
    x: float
    y_top: float
    title: str
    body_text: str


@dataclass(frozen=True)
class ParseMatchDecision:
    front_source_order: int | None
    back_source_order: int | None
    decision_status: str
    decision_reason: str
    matcher_raw_response: str


@dataclass(frozen=True)
class ArticleSource:
    source_order: int
    fragment_role: str
    sequence_index: int


@dataclass(frozen=True)
class ParsedArticle:
    article_order: int
    primary_source_order: int
    source_fragment_count: int
    title: str
    body_text: str
    source_fragments: list[ArticleSource]


@dataclass(frozen=True)
class ParseResult:
    fragments: list[ArticleFragment]
    match_decisions: list[ParseMatchDecision]
    articles: list[ParsedArticle]


def split_pdf_into_single_page_files(*, pdf_path: Path, output_dir: Path) -> list[SinglePagePdf]:
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(pdf_path))
    page_files: list[SinglePagePdf] = []
    for zero_based_index, page in enumerate(reader.pages):
        page_number = zero_based_index + 1
        writer = PdfWriter()
        writer.add_page(page)
        page_path = output_dir / f"page-{page_number:04d}.pdf"
        with page_path.open("wb") as output:
            writer.write(output)
        page_files.append(SinglePagePdf(page_number=page_number, path=page_path))
    return page_files


def extract_article_fragments_from_mineru_markdown(
    markdown_text: str,
    *,
    page_number: int = 0,
    starting_source_order: int = 1,
) -> list[ArticleFragment]:
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
                source_order=starting_source_order + len(fragments),
                continued_to_page=_extract_continued_to_page(body_text),
                continued_from_page=_extract_continued_from_page(body_text),
                page_number=page_number,
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
    parse_result = build_parse_result_from_mineru_markdown(
        markdown_text,
        continuation_matcher=continuation_matcher,
    )
    return [
        PageArticle(
            page_number=article.article_order,
            x=0.0,
            y_top=float(article.article_order),
            title=article.title,
            body_text=article.body_text,
        )
        for article in parse_result.articles
    ]


def parse_pdf_articles(
    path: Path,
    *,
    output_root: Path,
    mineru_client,
    continuation_matcher=None,
) -> list[PageArticle]:
    if hasattr(mineru_client, "parse_pdf_by_pages"):
        parsed_document = mineru_client.parse_pdf_by_pages(
            pdf_path=Path(path),
            output_root=Path(output_root),
        )
        parse_result = build_parse_result_from_mineru_pages(
            [
                ParsedMarkdownPage(
                    page_number=page.page_number,
                    markdown_text=page.markdown_text,
                )
                for page in parsed_document.pages
            ],
            continuation_matcher=continuation_matcher,
        )
        return [
            PageArticle(
                page_number=getattr(
                    parse_result.fragments[article.primary_source_order - 1],
                    "page_number",
                    article.article_order,
                ),
                x=0.0,
                y_top=float(article.article_order),
                title=article.title,
                body_text=article.body_text,
            )
            for article in parse_result.articles
        ]

    parsed_document = mineru_client.parse_pdf(pdf_path=Path(path), output_root=Path(output_root))
    return extract_articles_from_mineru_markdown(
        parsed_document.markdown_text,
        continuation_matcher=continuation_matcher,
    )


def build_parse_result_from_mineru_markdown(
    markdown_text: str,
    *,
    continuation_matcher=None,
) -> ParseResult:
    fragments = extract_article_fragments_from_mineru_markdown(markdown_text)
    return _build_parse_result_from_fragments(
        fragments,
        continuation_matcher=continuation_matcher,
    )


def build_parse_result_from_mineru_pages(
    pages: list[ParsedMarkdownPage],
    *,
    continuation_matcher=None,
) -> ParseResult:
    fragments: list[ArticleFragment] = []
    next_source_order = 1
    for page in sorted(pages, key=lambda item: item.page_number):
        page_fragments = extract_article_fragments_from_mineru_markdown(
            page.markdown_text,
            page_number=page.page_number,
            starting_source_order=next_source_order,
        )
        fragments.extend(page_fragments)
        next_source_order += len(page_fragments)
    return _build_parse_result_from_fragments(
        fragments,
        continuation_matcher=continuation_matcher,
    )


def _build_parse_result_from_fragments(
    fragments: list[ArticleFragment],
    *,
    continuation_matcher=None,
) -> ParseResult:
    match_decisions: list[ParseMatchDecision] = []

    if continuation_matcher is None:
        accepted_matches: list[tuple[int, int]] = []
    else:
        continuation_fragments = [
            fragment
            for fragment in fragments
            if fragment.continued_to_page or fragment.continued_from_page
        ]
        try:
            raw_matches = continuation_matcher(continuation_fragments)
        except Exception:
            raw_matches = []
        accepted_matches, match_decisions = _normalize_match_decisions(
            fragments,
            raw_matches=raw_matches,
        )

    return ParseResult(
        fragments=fragments,
        match_decisions=match_decisions,
        articles=_build_parsed_articles(
            fragments,
            accepted_matches=accepted_matches,
        ),
    )


def _normalize_match_decisions(
    fragments: list[ArticleFragment],
    *,
    raw_matches,
) -> tuple[list[tuple[int, int]], list[ParseMatchDecision]]:
    fragments_by_order = {fragment.source_order: fragment for fragment in fragments}
    used_source_orders: set[int] = set()
    accepted_matches: list[tuple[int, int]] = []
    match_decisions: list[ParseMatchDecision] = []

    for raw_match in raw_matches:
        raw_response = repr(raw_match)
        if not isinstance(raw_match, (tuple, list)) or len(raw_match) != 2:
            match_decisions.append(
                ParseMatchDecision(
                    front_source_order=None,
                    back_source_order=None,
                    decision_status="invalid",
                    decision_reason="match response must be a pair of source orders",
                    matcher_raw_response=raw_response,
                )
            )
            continue

        front_order, back_order = raw_match
        if not isinstance(front_order, int) or not isinstance(back_order, int):
            match_decisions.append(
                ParseMatchDecision(
                    front_source_order=None,
                    back_source_order=None,
                    decision_status="invalid",
                    decision_reason="match response must use integer source orders",
                    matcher_raw_response=raw_response,
                )
            )
            continue

        front_fragment = fragments_by_order.get(front_order)
        back_fragment = fragments_by_order.get(back_order)
        if front_fragment is None or back_fragment is None:
            match_decisions.append(
                ParseMatchDecision(
                    front_source_order=front_order,
                    back_source_order=back_order,
                    decision_status="invalid",
                    decision_reason="unknown fragment source order",
                    matcher_raw_response=raw_response,
                )
            )
            continue

        if front_order == back_order:
            match_decisions.append(
                ParseMatchDecision(
                    front_source_order=front_order,
                    back_source_order=back_order,
                    decision_status="invalid",
                    decision_reason="cannot match a fragment to itself",
                    matcher_raw_response=raw_response,
                )
            )
            continue

        if front_order in used_source_orders or back_order in used_source_orders:
            match_decisions.append(
                ParseMatchDecision(
                    front_source_order=front_order,
                    back_source_order=back_order,
                    decision_status="ignored",
                    decision_reason="fragment already matched by an earlier accepted pair",
                    matcher_raw_response=raw_response,
                )
            )
            continue

        if not front_fragment.continued_to_page or not back_fragment.continued_from_page:
            match_decisions.append(
                ParseMatchDecision(
                    front_source_order=front_order,
                    back_source_order=back_order,
                    decision_status="invalid",
                    decision_reason="fragments are not a valid continuation pair",
                    matcher_raw_response=raw_response,
                )
            )
            continue

        used_source_orders.add(front_order)
        used_source_orders.add(back_order)
        accepted_matches.append((front_order, back_order))
        match_decisions.append(
            ParseMatchDecision(
                front_source_order=front_order,
                back_source_order=back_order,
                decision_status="accepted",
                decision_reason="accepted continuation pair",
                matcher_raw_response=raw_response,
            )
        )

    return accepted_matches, match_decisions


def _build_parsed_articles(
    fragments: list[ArticleFragment],
    *,
    accepted_matches: list[tuple[int, int]],
) -> list[ParsedArticle]:
    fragments_by_order = {fragment.source_order: fragment for fragment in fragments}
    matched_back_orders = {back_order for _, back_order in accepted_matches}
    accepted_by_front_order = {
        front_order: back_order
        for front_order, back_order in accepted_matches
    }
    articles: list[ParsedArticle] = []

    for fragment in fragments:
        if fragment.source_order in matched_back_orders:
            continue

        back_order = accepted_by_front_order.get(fragment.source_order)
        if back_order is None:
            articles.append(
                ParsedArticle(
                    article_order=len(articles) + 1,
                    primary_source_order=fragment.source_order,
                    source_fragment_count=1,
                    title=fragment.title,
                    body_text=fragment.body_text,
                    source_fragments=[
                        ArticleSource(
                            source_order=fragment.source_order,
                            fragment_role="standalone",
                            sequence_index=1,
                        )
                    ],
                )
            )
            continue

        back_fragment = fragments_by_order[back_order]
        articles.append(
            ParsedArticle(
                article_order=len(articles) + 1,
                primary_source_order=fragment.source_order,
                source_fragment_count=2,
                title=fragment.title,
                body_text=_merge_fragment_body_text(fragment, back_fragment),
                source_fragments=[
                    ArticleSource(
                        source_order=fragment.source_order,
                        fragment_role="front",
                        sequence_index=1,
                    ),
                    ArticleSource(
                        source_order=back_fragment.source_order,
                        fragment_role="back",
                        sequence_index=2,
                    ),
                ],
            )
        )

    return articles


_CONTINUED_TO_TRIANGLE = re.compile(r"[►▶]\s*(\d+)")
_CONTINUED_FROM_TRIANGLE = re.compile(r"[◄◀]\s*(\d+)")


def _extract_continued_to_page(body_text: str) -> str:
    match = re.search(r"please\s*turn\s*to\s*page\s*([A-Z]\d+)", body_text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    triangle = _CONTINUED_TO_TRIANGLE.search(body_text)
    if triangle:
        return triangle.group(1)
    return ""


def _extract_continued_from_page(body_text: str) -> str:
    match = re.search(
        r"continued\s*from\s*(PageOne|page\s*[A-Z]\d+)",
        body_text,
        re.IGNORECASE,
    )
    if match:
        value = re.sub(r"\s+", "", match.group(1))
        if value.lower() == "pageone":
            return "PageOne"
        return value.removeprefix("page").removeprefix("Page")
    triangle = _CONTINUED_FROM_TRIANGLE.search(body_text)
    if triangle:
        return triangle.group(1)
    return ""


def _merge_fragment_body_text(front_fragment: ArticleFragment, back_fragment: ArticleFragment) -> str:
    front_body = re.sub(
        r"\n?please\s*turn\s*to\s*page\s*[A-Z]\d+\s*$",
        "",
        front_fragment.body_text,
        flags=re.IGNORECASE,
    )
    front_body = re.sub(r"\s*[►▶]\s*\d+\s*$", "", front_body).rstrip()
    back_body = re.sub(
        r"^continued\s*from\s*(?:PageOne|page\s*[A-Z]\d+)\s*",
        "",
        back_fragment.body_text,
        flags=re.IGNORECASE,
    )
    back_body = re.sub(r"^\s*[◄◀]\s*\d+\s*", "", back_body).lstrip()
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
