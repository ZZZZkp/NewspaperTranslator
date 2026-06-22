"""Filename-derived document metadata: newspaper label and issue date.

Pure helpers with no project dependencies, shared by ingestion (issue identity)
and the article pipeline (publication date). Filename date forms here are
distinct from the markdown comma-form written-date parser in article_pipeline.
"""
from __future__ import annotations

import unicodedata

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
