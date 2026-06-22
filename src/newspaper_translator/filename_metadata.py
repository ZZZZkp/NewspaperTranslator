"""Filename-derived document metadata: newspaper label and issue date.

Pure helpers with no project dependencies, shared by ingestion (issue identity)
and the article pipeline (publication date). Filename date forms here are
distinct from the markdown comma-form written-date parser in article_pipeline.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_GMAIL_MESSAGE_TZ = ZoneInfo("Asia/Shanghai")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO_RE = re.compile(r"(\d{4})[-_/](\d{1,2})[-_/](\d{1,2})")
_WRITTEN_RE = re.compile(
    rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE
)
_MONTH_YEAR_RE = re.compile(rf"\b({_MONTH_PATTERN})\s+(\d{{4}})\b", re.IGNORECASE)
_MONTH_DAY_RE = re.compile(r"[-_](\d{1,2})[-_](\d{1,2})$")

# Leading filename prefix (case-insensitive, startswith) -> newspaper label.
# The longest matching alias wins, so "the economist usa" beats "the economist".
PUBLISHER_ALIASES: dict[str, str] = {
    "the economist usa": "经济学人",
    "the economist": "经济学人",
    "bloomberg businessweek usa": "彭博商业周刊",
    "bloomberg businessweek": "彭博商业周刊",
}


def match_publisher_alias(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    best_label: str | None = None
    best_len = -1
    for alias, label in PUBLISHER_ALIASES.items():
        if normalized.startswith(alias) and len(alias) > best_len:
            best_label = label
            best_len = len(alias)
    return best_label


def extract_filename_date(
    filename: str,
    *,
    source_message_internal_date: str | None = None,
    fallback_year: int | None = None,
) -> str:
    stem = unicodedata.normalize("NFKC", Path(filename).name)
    stem = Path(stem).stem

    iso = _ISO_RE.search(stem)
    if iso:
        return _normalize(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    written = _WRITTEN_RE.search(stem)
    if written:
        return _normalize(
            int(written.group(3)), _MONTHS[written.group(1).lower()], int(written.group(2))
        )

    month_year = _MONTH_YEAR_RE.search(stem)
    if month_year:
        return _normalize(int(month_year.group(2)), _MONTHS[month_year.group(1).lower()], 1)

    month_day = _MONTH_DAY_RE.search(stem)
    if month_day:
        gmail_dt = _gmail_datetime(source_message_internal_date)
        year = gmail_dt.year if gmail_dt else (fallback_year or datetime.now().year)
        return _normalize(year, int(month_day.group(1)), int(month_day.group(2)))

    return ""


def _normalize(year: int, month: int, day: int) -> str:
    try:
        return datetime(year=year, month=month, day=day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _gmail_datetime(message_internal_date: str | None) -> datetime | None:
    if not message_internal_date:
        return None
    try:
        timestamp_ms = int(message_internal_date)
    except ValueError:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).astimezone(_GMAIL_MESSAGE_TZ)
