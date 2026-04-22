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


def extract_title_candidates(path: Path, *, page_number: int) -> list[str]:
    candidates: list[str] = []
    for block in extract_page_text_blocks(path, page_number=page_number):
        if _looks_like_title_candidate(block.text):
            candidates.append(block.text)
    return candidates


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
