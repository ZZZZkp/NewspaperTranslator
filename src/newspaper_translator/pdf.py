from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class PdfInspection:
    path: Path
    page_count: int
    extractable_page_count: int

    @property
    def has_extractable_text(self) -> bool:
        return self.extractable_page_count > 0


@dataclass(frozen=True)
class PdfPageProfile:
    page_number: int
    text_length: int
    has_extractable_text: bool
    page_type: str


@dataclass(frozen=True)
class ExtractedTextPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class PdfTextBlock:
    page_number: int
    block_number: int
    text: str


@dataclass(frozen=True)
class PositionedTextFragment:
    page_number: int
    x: float
    y: float
    font_size: float
    text: str


@dataclass(frozen=True)
class PositionedTextBlock:
    page_number: int
    x: float
    y_top: float
    y_bottom: float
    line_count: int
    text: str


@dataclass(frozen=True)
class ArticleCandidateBlock:
    page_number: int
    x: float
    y_top: float
    title: str
    body_text: str


@dataclass(frozen=True)
class PageArticle:
    page_number: int
    x: float
    y_top: float
    title: str
    body_text: str


def inspect_pdf(path: Path) -> PdfInspection:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))

    extractable_page_count = 0
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            extractable_page_count += 1

    return PdfInspection(
        path=pdf_path,
        page_count=len(reader.pages),
        extractable_page_count=extractable_page_count,
    )


def classify_pdf(path: Path) -> str:
    inspection = inspect_pdf(path)
    if inspection.has_extractable_text:
        return "digital"
    return "scanned"


def extract_page_text(path: Path, *, page_number: int) -> str:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))

    if page_number < 1 or page_number > len(reader.pages):
        raise IndexError(f"Page number {page_number} is out of range for {pdf_path.name}")

    return (reader.pages[page_number - 1].extract_text() or "").strip()


def build_page_profiles(path: Path) -> list[PdfPageProfile]:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))
    profiles: list[PdfPageProfile] = []

    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        has_extractable_text = bool(text)
        profiles.append(
            PdfPageProfile(
                page_number=index,
                text_length=len(text),
                has_extractable_text=has_extractable_text,
                page_type="digital" if has_extractable_text else "scanned",
            )
        )

    return profiles


def extract_text_pages(path: Path) -> list[ExtractedTextPage]:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))
    pages: list[ExtractedTextPage] = []

    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(ExtractedTextPage(page_number=index, text=text))

    return pages


def extract_page_text_blocks(path: Path, *, page_number: int) -> list[PdfTextBlock]:
    text = extract_page_text(path, page_number=page_number)
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [
        PdfTextBlock(page_number=page_number, block_number=index, text=line)
        for index, line in enumerate(lines, start=1)
    ]


def extract_positioned_text_fragments(path: Path, *, page_number: int) -> list[PositionedTextFragment]:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))

    if page_number < 1 or page_number > len(reader.pages):
        raise IndexError(f"Page number {page_number} is out of range for {pdf_path.name}")

    fragments: list[PositionedTextFragment] = []

    def visitor_text(
        text: str,
        _cm: list[float],
        tm: list[float],
        _font_dict: dict[str, object] | None,
        font_size: float,
    ) -> None:
        normalized = (text or "").strip()
        if not normalized:
            return

        fragments.append(
            PositionedTextFragment(
                page_number=page_number,
                x=round(float(tm[4]), 1),
                y=round(float(tm[5]), 1),
                font_size=round(float(font_size), 1),
                text=normalized,
            )
        )

    reader.pages[page_number - 1].extract_text(visitor_text=visitor_text)
    fragments.sort(key=lambda fragment: (-fragment.y, fragment.x, fragment.text))
    return fragments


def build_positioned_text_blocks(path: Path, *, page_number: int) -> list[PositionedTextBlock]:
    fragments = extract_positioned_text_fragments(path, page_number=page_number)
    if not fragments:
        return []

    blocks: list[PositionedTextBlock] = []
    x_sorted_fragments = sorted(fragments, key=lambda fragment: (fragment.x, -fragment.y, fragment.text))
    x_groups: list[list[PositionedTextFragment]] = [[x_sorted_fragments[0]]]

    def append_block(block_fragments: list[PositionedTextFragment]) -> None:
        if not block_fragments:
            return

        ordered_fragments = sorted(block_fragments, key=lambda fragment: (-fragment.y, fragment.x))
        blocks.append(
            PositionedTextBlock(
                page_number=page_number,
                x=round(ordered_fragments[0].x, 1),
                y_top=round(max(fragment.y for fragment in ordered_fragments), 1),
                y_bottom=round(min(fragment.y for fragment in ordered_fragments), 1),
                line_count=len(ordered_fragments),
                text="\n".join(fragment.text for fragment in ordered_fragments),
            )
        )

    for fragment in x_sorted_fragments[1:]:
        current_x_group = x_groups[-1]
        x_anchor = current_x_group[0].x
        if abs(fragment.x - x_anchor) <= 25.0:
            current_x_group.append(fragment)
            continue
        x_groups.append([fragment])

    for x_group in x_groups:
        y_sorted_fragments = sorted(x_group, key=lambda fragment: (-fragment.y, fragment.x, fragment.text))
        current_block_fragments: list[PositionedTextFragment] = [y_sorted_fragments[0]]

        for fragment in y_sorted_fragments[1:]:
            previous = current_block_fragments[-1]
            if (previous.y - fragment.y) <= 30.0:
                current_block_fragments.append(fragment)
                continue

            append_block(current_block_fragments)
            current_block_fragments = [fragment]

        append_block(current_block_fragments)

    blocks.sort(key=lambda block: (-block.y_top, block.x, block.text))
    return blocks


def extract_article_candidate_blocks(path: Path, *, page_number: int) -> list[ArticleCandidateBlock]:
    candidates: list[ArticleCandidateBlock] = []

    for block in build_positioned_text_blocks(path, page_number=page_number):
        lines = [
            line.strip()
            for line in block.text.splitlines()
            if line.strip() and not _looks_like_symbol_fragment(line)
        ]
        if not lines:
            continue

        title_start_index = None
        for index, line in enumerate(lines):
            if _looks_like_layout_noise(line):
                continue
            if _looks_like_title_candidate(line):
                title_start_index = index
                break

        if title_start_index is None:
            continue

        title = lines[title_start_index]
        body_lines: list[str] = []
        for line in lines[title_start_index + 1 :]:
            if _looks_like_layout_noise(line) or _looks_like_reference_marker(line):
                continue
            if body_lines and body_lines[-1].endswith(".") and _looks_like_compact_headline_token(line):
                break
            body_lines.append(line)

        if not body_lines:
            continue

        candidates.append(
            ArticleCandidateBlock(
                page_number=block.page_number,
                x=block.x,
                y_top=block.y_top,
                title=title,
                body_text="\n".join(body_lines),
            )
        )

    return candidates


def extract_page_articles(path: Path, *, page_number: int) -> list[PageArticle]:
    candidates = extract_article_candidate_blocks(path, page_number=page_number)
    if not candidates:
        return []

    x_sorted_candidates = sorted(candidates, key=lambda candidate: (candidate.x, -candidate.y_top, candidate.title))
    x_groups: list[list[ArticleCandidateBlock]] = [[x_sorted_candidates[0]]]

    for candidate in x_sorted_candidates[1:]:
        current_x_group = x_groups[-1]
        x_anchor = current_x_group[0].x
        if abs(candidate.x - x_anchor) <= 25.0:
            current_x_group.append(candidate)
            continue
        x_groups.append([candidate])

    articles: list[PageArticle] = []
    for x_group in x_groups:
        ordered_candidates = sorted(x_group, key=lambda candidate: (-candidate.y_top, candidate.x, candidate.title))
        index = 0
        while index < len(ordered_candidates):
            candidate = ordered_candidates[index]
            if index > 0 and _looks_like_continuation_title(candidate.title):
                index += 1
                continue
            if _looks_like_byline_line(candidate.title):
                index += 1
                continue

            body_lines = [line for line in candidate.body_text.splitlines() if line.strip()]
            next_index = index + 1
            while next_index < len(ordered_candidates):
                following_candidate = ordered_candidates[next_index]
                if _looks_like_byline_line(following_candidate.title):
                    if (candidate.y_top - following_candidate.y_top) > 90.0:
                        break
                    body_lines.append(following_candidate.title)
                    body_lines.extend(
                        line for line in following_candidate.body_text.splitlines() if line.strip()
                    )
                    next_index += 1
                    continue
                if not _looks_like_continuation_title(following_candidate.title):
                    break
                if (candidate.y_top - following_candidate.y_top) > 180.0:
                    break

                body_lines.append(following_candidate.title)
                body_lines.extend(
                    line for line in following_candidate.body_text.splitlines() if line.strip()
                )
                next_index += 1

            articles.append(
                PageArticle(
                    page_number=candidate.page_number,
                    x=candidate.x,
                    y_top=candidate.y_top,
                    title=candidate.title,
                    body_text="\n".join(body_lines),
                )
            )
            index = next_index

    articles.sort(key=lambda article: (-article.y_top, article.x, article.title))
    return articles


def extract_title_candidates(path: Path, *, page_number: int) -> list[str]:
    candidates: list[str] = []
    for block in extract_page_text_blocks(path, page_number=page_number):
        if _looks_like_title_candidate(block.text):
            candidates.append(block.text)
    return candidates


def extract_articles_from_mineru_markdown(markdown_text: str) -> list[PageArticle]:
    articles: list[PageArticle] = []
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

        articles.append(
            PageArticle(
                page_number=len(articles) + 1,
                x=0.0,
                y_top=float(len(articles) + 1),
                title=current_title,
                body_text="\n".join(current_body_lines),
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

    return articles


def parse_pdf_articles(path: Path, *, output_root: Path, mineru_client) -> list[PageArticle]:
    parsed_document = mineru_client.parse_pdf(pdf_path=Path(path), output_root=Path(output_root))
    return extract_articles_from_mineru_markdown(parsed_document.markdown_text)


def _looks_like_title_candidate(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False

    lower = normalized.lower()
    banned_prefixes = (
        "section:",
        "by ",
        "lastweek:",
        "tuesday",
        "from £",
        "news page",
    )
    if lower.startswith(banned_prefixes):
        return False

    banned_substrings = (
        "edition date",
        "sent at",
        "wsj.com",
    )
    if any(part in lower for part in banned_substrings):
        return False

    if len(normalized) < 8 or len(normalized) > 60:
        return False

    alpha_count = sum(char.isalpha() for char in normalized)
    digit_count = sum(char.isdigit() for char in normalized)
    if alpha_count < 6 or digit_count > 4:
        return False

    words = normalized.split()
    if len(words) < 2:
        return False

    # Prefer headline-like fragments over bylines/body text.
    if normalized.endswith((".", ":")):
        return False

    return True


def _looks_like_layout_noise(text: str) -> bool:
    normalized = text.strip()
    lower = normalized.lower()
    if lower in {"what’s", "news", "business & finance"}:
        return True
    if lower.startswith(("section:", "edition date:", "sent at ", "wsj.com", "lastweek:")):
        return True
    return False


def _looks_like_symbol_fragment(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return True
    return not any(char.isalnum() for char in normalized)


def _looks_like_reference_marker(text: str) -> bool:
    normalized = text.strip()
    if len(normalized) not in {2, 3}:
        return False
    return normalized[0].isalpha() and normalized[1:].isdigit()


def _looks_like_continuation_title(text: str) -> bool:
    normalized = text.strip()
    return bool(normalized) and normalized[0].islower()


def _looks_like_compact_headline_token(text: str) -> bool:
    normalized = text.strip()
    if " " in normalized or len(normalized) < 8:
        return False
    has_upper = any(char.isupper() for char in normalized)
    has_lower = any(char.islower() for char in normalized)
    return has_upper and has_lower


def _looks_like_byline_line(text: str) -> bool:
    normalized = text.strip()
    words = [word for word in normalized.split() if word]
    if len(words) < 2 or len(words) > 3:
        return False

    for word in words:
        letters = "".join(char for char in word if char.isalpha() or char in {"’", "'"})
        if len(letters) < 2:
            return False
        first_alpha_index = next((index for index, char in enumerate(letters) if char.isalpha()), None)
        if first_alpha_index is None:
            return False
        first_alpha = letters[first_alpha_index]
        if not first_alpha.isupper():
            return False
        trailing_letters = "".join(char for char in letters[first_alpha_index + 1 :] if char.isalpha())
        if trailing_letters and not trailing_letters.islower():
            return False

    return True


def _looks_like_mineru_byline_heading(text: str) -> bool:
    normalized = text.strip()
    return normalized.upper().startswith("BY ") and len(normalized) > 3


def _looks_like_mineru_heading_noise(text: str) -> bool:
    normalized = text.strip()
    lower = normalized.lower()
    if not normalized or _looks_like_symbol_fragment(normalized):
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
