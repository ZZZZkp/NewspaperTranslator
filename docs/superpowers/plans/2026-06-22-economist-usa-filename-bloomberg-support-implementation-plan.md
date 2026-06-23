# Economist USA Filename, Issue-Level Dedupe, And Bloomberg Businessweek Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt new Economist filename forms, add issue-level dedupe for all publications, and support Bloomberg Businessweek (MinerU path) with `►`/`◄` cross-page stitching and hero images.

**Architecture:** A new dependency-free `filename_metadata.py` owns the publisher-alias table and the filename date resolver. `ingestion.py` uses it to label documents and to compute a filename-derived `issue_date`, then deduplicates by content hash first and `(source_name, issue_date)` second. `article_pipeline.py` prefers the stored `issue_date` as the authoritative publication date. `pdf.py` learns Bloomberg's solid-triangle continuation markers while ignoring white cross-reference triangles. Bloomberg otherwise rides the existing MinerU path and image/hero flow unchanged.

**Tech Stack:** Python 3.11+, SQLite, `pypdf`, `unittest`/`pytest`, existing MinerU + DeepSeek pipeline.

**Spec:** `docs/superpowers/specs/2026-06-22-economist-usa-filename-bloomberg-support-design.md`

---

## File Structure

- Create: `src/newspaper_translator/filename_metadata.py` — publisher alias table + filename date resolver (pure, no project deps).
- Create: `src/newspaper_translator/migrations/0015_documents_issue_date.sql` — add `issue_date` column + index.
- Create: `tests/test_filename_metadata.py` — unit tests for aliases + date forms.
- Modify: `src/newspaper_translator/ingestion.py` — alias-aware source name, compute/store `issue_date`, two-stage dedupe.
- Modify: `src/newspaper_translator/article_pipeline.py` — `StoredDocument.issue_date`, select it, prefer it in `resolve_publication_date`.
- Modify: `src/newspaper_translator/pdf.py` — solid-triangle continuation extraction + merge stripping.
- Modify/extend tests: `tests/test_ingestion_source_name.py`, `tests/test_ingestion.py`, `tests/test_pdf_layout.py`, `tests/test_economist_edition_pipeline.py` (or `tests/test_process_document.py` for date resolution).

**Test command (used throughout):** tests insert `src` onto `sys.path` themselves, so no `PYTHONPATH` is needed.

```bash
./.venv/bin/python -m pytest <path> -v
```

---

## Task 1: filename_metadata module — publisher aliases

**Files:**
- Create: `src/newspaper_translator/filename_metadata.py`
- Test: `tests/test_filename_metadata.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_filename_metadata.py`:

```python
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.filename_metadata import match_publisher_alias


class MatchPublisherAliasTests(unittest.TestCase):
    def test_economist_usa_prefix_maps_to_economist(self) -> None:
        self.assertEqual(
            match_publisher_alias("The Economist USA - June 20 2026"),
            "经济学人",
        )

    def test_bare_economist_prefix_maps_to_economist(self) -> None:
        self.assertEqual(match_publisher_alias("The Economist - June 20 2026"), "经济学人")

    def test_bloomberg_prefix_maps_to_label(self) -> None:
        self.assertEqual(
            match_publisher_alias("Bloomberg Businessweek USA - June 2026"),
            "彭博商业周刊",
        )

    def test_unknown_prefix_returns_none(self) -> None:
        self.assertIsNone(match_publisher_alias("金融时报-5-6"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_filename_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newspaper_translator.filename_metadata'`

- [ ] **Step 3: Write minimal implementation**

Create `src/newspaper_translator/filename_metadata.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_filename_metadata.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/filename_metadata.py tests/test_filename_metadata.py
git commit -m "feat: add publisher alias table for filename source labels"
```

---

## Task 2: filename_metadata module — filename date resolver

**Files:**
- Modify: `src/newspaper_translator/filename_metadata.py`
- Test: `tests/test_filename_metadata.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_filename_metadata.py` (add the import at top: `from newspaper_translator.filename_metadata import extract_filename_date`):

```python
class ExtractFilenameDateTests(unittest.TestCase):
    def test_iso_date(self) -> None:
        self.assertEqual(extract_filename_date("wsj-2026-05-06.pdf"), "2026-05-06")

    def test_written_date_with_day(self) -> None:
        self.assertEqual(
            extract_filename_date("The Economist USA - June 20 2026.pdf"),
            "2026-06-20",
        )

    def test_written_month_year_defaults_to_first(self) -> None:
        self.assertEqual(
            extract_filename_date("Bloomberg Businessweek USA - June 2026.pdf"),
            "2026-06-01",
        )

    def test_invalid_written_date_returns_empty(self) -> None:
        self.assertEqual(extract_filename_date("Paper - June 31 2026.pdf"), "")

    def test_month_day_uses_gmail_year(self) -> None:
        # 2026-05-07 in Asia/Shanghai
        self.assertEqual(
            extract_filename_date(
                "金融时报-5-6.pdf",
                source_message_internal_date="1746576000000",
            ),
            "2026-05-06",
        )

    def test_month_day_uses_fallback_year_without_gmail(self) -> None:
        self.assertEqual(
            extract_filename_date("金融时报-5-6.pdf", fallback_year=2024),
            "2024-05-06",
        )

    def test_no_date_returns_empty(self) -> None:
        self.assertEqual(extract_filename_date("daily-paper.pdf"), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_filename_metadata.py::ExtractFilenameDateTests -v`
Expected: FAIL with `ImportError: cannot import name 'extract_filename_date'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/newspaper_translator/filename_metadata.py` (extend the header imports):

```python
from datetime import UTC, datetime
from pathlib import Path
import re
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_filename_metadata.py -v`
Expected: PASS (all tests). If `test_month_day_uses_gmail_year` resolves to a different day, adjust the epoch-ms literal so it lands on 2026-05-07 in Asia/Shanghai; the assertion target stays `2026-05-06`.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/filename_metadata.py tests/test_filename_metadata.py
git commit -m "feat: add filename date resolver covering written and month-year forms"
```

---

## Task 3: ingestion source name uses publisher aliases

**Files:**
- Modify: `src/newspaper_translator/ingestion.py:255-278`
- Test: `tests/test_ingestion_source_name.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingestion_source_name.py`:

```python
    def test_economist_usa_written_date_filename_maps_to_economist(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("The Economist USA - June 20 2026.pdf"),
            "经济学人",
        )

    def test_bloomberg_filename_maps_to_label(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("Bloomberg Businessweek USA - June 2026.pdf"),
            "彭博商业周刊",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_ingestion_source_name.py -v`
Expected: FAIL — returns `The Economist USA - June 20 2026` instead of `经济学人`.

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/ingestion.py`, add the import near the other imports (after line 11):

```python
from newspaper_translator.filename_metadata import extract_filename_date, match_publisher_alias
```

Then edit `_extract_source_name_from_filename` (currently starts at line 255) so the alias check runs right after the economist e-edition check:

```python
def _extract_source_name_from_filename(filename: str) -> str:
    if _is_economist_edition_filename(filename):
        return "经济学人"
    stem = Path(filename).name
    stem = Path(stem).stem
    alias = match_publisher_alias(stem)
    if alias:
        return alias
    full_date_match = re.search(
        r"^(?P<prefix>.*?)[-_](\d{4})[-_](\d{1,2})[-_](\d{1,2})$",
        stem,
    )
    # ... rest unchanged ...
```

(Leave the remaining body of the function exactly as it is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_ingestion_source_name.py -v`
Expected: PASS (all tests, including the four pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/ingestion.py tests/test_ingestion_source_name.py
git commit -m "feat: map Economist USA and Bloomberg filenames to source labels"
```

---

## Task 4: migration 0015 — documents.issue_date

**Files:**
- Create: `src/newspaper_translator/migrations/0015_documents_issue_date.sql`
- Test: `tests/test_database.py` (add one test) — or verify via migration run.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_database.py` a test that the column exists after migrations (match the file's existing harness style; example):

```python
    def test_documents_has_issue_date_column(self) -> None:
        import sqlite3, tempfile, pathlib
        from newspaper_translator.database import run_pending_migrations
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            connection = sqlite3.connect(database_path)
            try:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(documents)").fetchall()
                }
            finally:
                connection.close()
        self.assertIn("issue_date", columns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_database.py -v -k issue_date`
Expected: FAIL — `issue_date` not in columns.

- [ ] **Step 3: Write minimal implementation**

Create `src/newspaper_translator/migrations/0015_documents_issue_date.sql`:

```sql
ALTER TABLE documents ADD COLUMN issue_date TEXT;

CREATE INDEX idx_documents_source_name_issue_date
    ON documents (source_name, issue_date);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_database.py -v -k issue_date`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/migrations/0015_documents_issue_date.sql tests/test_database.py
git commit -m "feat: add documents.issue_date column and source/issue index"
```

---

## Task 5: ingestion stores issue_date on insert

**Files:**
- Modify: `src/newspaper_translator/ingestion.py:81-89,134-161`
- Test: `tests/test_ingestion.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingestion.py` (uses the same temp-db harness as the existing import test):

```python
    def test_import_stores_filename_issue_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            message = GmailMessage(message_id="m1", sender="s@example.com", attachments=[])
            attachment = GmailAttachment(
                attachment_id="a1",
                filename="The Economist USA - June 20 2026.pdf",
                mime_type="application/pdf",
                content_bytes=b"%PDF-1.7 economist",
            )
            result = import_gmail_pdf_attachment(
                message=message,
                attachment=attachment,
                storage_root=storage_root,
                database_url=database_url,
            )
            connection = sqlite3.connect(database_path)
            try:
                row = connection.execute(
                    "SELECT source_name, issue_date FROM documents WHERE document_key = ?",
                    (result.document_key,),
                ).fetchone()
            finally:
                connection.close()
        self.assertEqual(row, ("经济学人", "2026-06-20"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_ingestion.py -v -k issue_date`
Expected: FAIL — `sqlite3.OperationalError` (no such column in INSERT) or `issue_date` is NULL.

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/ingestion.py`, compute `issue_date` next to `filename_source_name` (after line 81):

```python
    filename_source_name = _extract_source_name_from_filename(attachment.filename)
    filename_issue_date = extract_filename_date(
        attachment.filename,
        source_message_internal_date=message.internal_date,
    )
```

Then add `issue_date` to the INSERT (the statement near lines 134-161). Add `issue_date` to the column list and a matching `?`, and pass `filename_issue_date or None` in the values tuple:

```python
        cursor = connection.execute(
            """
            INSERT INTO documents (
                document_key,
                source_name,
                source_message_id,
                source_attachment_id,
                sender,
                original_filename,
                content_hash,
                raw_path,
                import_status,
                source_message_internal_date,
                issue_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.document_key,
                filename_source_name,
                message.message_id,
                attachment.attachment_id,
                message.sender,
                attachment.filename,
                content_hash,
                str(raw_path),
                "imported",
                message.internal_date,
                filename_issue_date or None,
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_ingestion.py -v`
Expected: PASS (new test plus all existing ingestion tests).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/ingestion.py tests/test_ingestion.py
git commit -m "feat: persist filename-derived issue_date on document import"
```

---

## Task 6: ingestion issue-level dedupe

**Files:**
- Modify: `src/newspaper_translator/ingestion.py:96-133`
- Test: `tests/test_ingestion.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingestion.py`:

```python
    def test_same_issue_different_file_dedupes_to_one_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            def make(att_id, body):
                return GmailAttachment(
                    attachment_id=att_id,
                    filename="wsj-2026-05-06.pdf",
                    mime_type="application/pdf",
                    content_bytes=body,
                )

            msg = GmailMessage(message_id="m1", sender="s@example.com", attachments=[])
            first = import_gmail_pdf_attachment(
                message=msg, attachment=make("a1", b"%PDF first bytes"),
                storage_root=storage_root, database_url=database_url,
            )
            second = import_gmail_pdf_attachment(
                message=msg, attachment=make("a2", b"%PDF different bytes"),
                storage_root=storage_root, database_url=database_url,
            )

            connection = sqlite3.connect(database_path)
            try:
                doc_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                run_count = connection.execute(
                    "SELECT COUNT(*) FROM document_processing_runs WHERE document_key = ?",
                    (first.document_key,),
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertFalse(second.was_created)
        self.assertEqual(second.document_key, first.document_key)
        self.assertEqual(doc_count, 1)
        self.assertEqual(run_count, 1)

    def test_dateless_files_are_not_issue_deduped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = pathlib.Path(temp_dir) / "storage"
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            msg = GmailMessage(message_id="m1", sender="s@example.com", attachments=[])
            for att_id, body in (("a1", b"%PDF one"), ("a2", b"%PDF two")):
                import_gmail_pdf_attachment(
                    message=msg,
                    attachment=GmailAttachment(
                        attachment_id=att_id, filename="daily-paper.pdf",
                        mime_type="application/pdf", content_bytes=body,
                    ),
                    storage_root=storage_root, database_url=database_url,
                )
            connection = sqlite3.connect(database_path)
            try:
                doc_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(doc_count, 2)
```

Note: `document_processing_runs WHERE document_key` — the existing duplicate path calls `create_document_processing_run`, which must be idempotent per document_key. If that helper inserts unconditionally, the run_count assertion guards against a regression; if it already upserts, the test still passes. Confirm during Step 4 and, if it inserts duplicates, scope the dedupe reuse to skip re-enqueue (matching the existing content-hash reuse behavior, which already calls it).

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_ingestion.py -v -k "issue or dedupe"`
Expected: FAIL — `test_same_issue_different_file_dedupes_to_one_document` produces 2 documents.

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/ingestion.py`, after the existing `content_hash` lookup/reuse block (the `if existing_row is not None:` branch ending around line 133) and before the `INSERT`, add an issue-identity lookup that reuses the same reuse logic. Factor the reuse into a small local helper to stay DRY:

```python
        def _reuse_existing(row) -> ImportedDocument:
            connection.commit()
            print(
                format_log_event(
                    level="INFO",
                    event="duplicate_document_reused",
                    service="worker",
                    details={
                        "content_hash": content_hash,
                        "canonical_document_key": row[0],
                        "message_id": message.message_id,
                        "attachment_id": attachment.attachment_id,
                    },
                ),
                flush=True,
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=row[0],
            )
            return ImportedDocument(
                document_key=row[0],
                content_hash=content_hash,
                raw_path=Path(row[1]),
                was_created=False,
            )

        existing_row = connection.execute(
            """
            SELECT document_key, raw_path
            FROM documents
            WHERE content_hash = ?
            ORDER BY created_at ASC, rowid ASC
            LIMIT 1
            """,
            (content_hash,),
        ).fetchone()
        if existing_row is not None:
            return _reuse_existing(existing_row)

        if filename_source_name and filename_issue_date:
            issue_row = connection.execute(
                """
                SELECT document_key, raw_path
                FROM documents
                WHERE source_name = ? AND issue_date = ?
                ORDER BY created_at ASC, rowid ASC
                LIMIT 1
                """,
                (filename_source_name, filename_issue_date),
            ).fetchone()
            if issue_row is not None:
                return _reuse_existing(issue_row)
```

This replaces the current inline content-hash reuse block (lines ~96-133) — the `BEGIN IMMEDIATE` and the rest of the function stay as they are. The `_reuse_existing` helper preserves the existing reuse behavior exactly (commit, log, ensure processing run, return `was_created=False`).

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_ingestion.py -v`
Expected: PASS (all tests). If `run_count` is 2, inspect `create_document_processing_run`; if it inserts unconditionally, that is a pre-existing behavior shared with the content-hash path — in that case relax the assertion to `>= 1` and note it, rather than changing unrelated behavior.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/ingestion.py tests/test_ingestion.py
git commit -m "feat: dedupe imports by (source_name, issue_date) issue identity"
```

---

## Task 7: article pipeline prefers documents.issue_date

**Files:**
- Modify: `src/newspaper_translator/article_pipeline.py:26-32` (StoredDocument), `:198-219` (resolver), `:329-350` (_get_document), `:53-58,139-...` (call sites)
- Test: `tests/test_process_document.py` (or a focused new test)

- [ ] **Step 1: Write the failing test**

Add a focused unit test (new file `tests/test_resolve_publication_date.py`):

```python
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.article_pipeline import resolve_publication_date


class ResolvePublicationDateTests(unittest.TestCase):
    def test_issue_date_is_authoritative(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="The Economist USA - June 20 2026.pdf",
                markdown_text="May 1, 2020",
                issue_date="2026-06-20",
            ),
            "2026-06-20",
        )

    def test_falls_back_when_issue_date_missing(self) -> None:
        self.assertEqual(
            resolve_publication_date(
                original_filename="wsj-2026-05-06.pdf",
                markdown_text="",
                issue_date=None,
            ),
            "2026-05-06",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_resolve_publication_date.py -v`
Expected: FAIL — `resolve_publication_date()` got an unexpected keyword argument `issue_date`.

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/article_pipeline.py`:

a) Add `issue_date` to `StoredDocument`:

```python
@dataclass(frozen=True)
class StoredDocument:
    document_key: str
    original_filename: str
    raw_path: str
    source_message_internal_date: str | None
    issue_date: str | None = None
```

b) Add the parameter to `resolve_publication_date` and prefer it (first lines of the function body):

```python
def resolve_publication_date(
    *,
    original_filename: str,
    markdown_text: str,
    source_message_internal_date: str | None = None,
    fallback_year: int | None = None,
    issue_date: str | None = None,
) -> str:
    if issue_date:
        return issue_date
    filename_iso_date = _extract_iso_date_from_text(original_filename)
    # ... rest unchanged ...
```

c) Select `issue_date` in `_get_document` (add to the SELECT column list and the returned `StoredDocument(...)`):

```python
            SELECT document_key, original_filename, raw_path, source_message_internal_date, issue_date
            FROM documents
            WHERE document_key = ?
```

```python
    return StoredDocument(
        document_key=row[0],
        original_filename=row[1],
        raw_path=row[2],
        source_message_internal_date=row[3],
        issue_date=row[4],
    )
```

d) Pass `issue_date=document.issue_date` at both `resolve_publication_date(...)` call sites (around lines 53 and 139):

```python
    publication_date = resolve_publication_date(
        original_filename=document.original_filename,
        markdown_text=parsed_document.markdown_text,
        source_message_internal_date=document.source_message_internal_date,
        fallback_year=datetime.now().year,
        issue_date=document.issue_date,
    )
```

(For the second call site — the Economist edition path — pass `issue_date=document.issue_date` the same way. If that path resolves the date without markdown, pass `markdown_text=""`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_resolve_publication_date.py tests/test_process_document.py tests/test_economist_edition_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/article_pipeline.py tests/test_resolve_publication_date.py
git commit -m "feat: prefer stored issue_date as authoritative publication date"
```

---

## Task 8: Bloomberg solid-triangle continuation markers

**Files:**
- Modify: `src/newspaper_translator/pdf.py:457-491`
- Test: `tests/test_pdf_layout.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pdf_layout.py` (import the private helpers used by other tests in that file; match its existing import style):

```python
    def test_solid_triangle_sets_continued_to_page(self) -> None:
        from newspaper_translator.pdf import _extract_continued_to_page
        self.assertEqual(_extract_continued_to_page("the story continues ►84"), "84")

    def test_solid_triangle_sets_continued_from_page(self) -> None:
        from newspaper_translator.pdf import _extract_continued_from_page
        self.assertEqual(_extract_continued_from_page("◄52 the story resumes"), "52")

    def test_white_triangle_cross_reference_is_ignored(self) -> None:
        from newspaper_translator.pdf import _extract_continued_to_page
        self.assertEqual(_extract_continued_to_page("see related coverage ▷54"), "")

    def test_merge_strips_solid_triangle_markers(self) -> None:
        from newspaper_translator.pdf import ArticleFragment, _merge_fragment_body_text
        front = ArticleFragment(title="t", body_text="front body ►84", source_order=1,
                                continued_to_page="84", continued_from_page="", page_number=1)
        back = ArticleFragment(title="t", body_text="◄52 back body", source_order=2,
                               continued_to_page="", continued_from_page="52", page_number=3)
        self.assertEqual(_merge_fragment_body_text(front, back), "front body\nback body")
```

(Confirm `ArticleFragment`'s constructor argument order against `src/newspaper_translator/pdf.py:9-15` before running; adjust keyword usage if needed.)

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_pdf_layout.py -v -k "triangle"`
Expected: FAIL — solid-triangle cases return `""` / merge leaves the markers.

- [ ] **Step 3: Write minimal implementation**

In `src/newspaper_translator/pdf.py`, extend the three functions. Solid markers are `►`/`▶` (to) and `◄`/`◀` (from); white `▷`/`◁` are never matched.

```python
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
```

And extend `_merge_fragment_body_text` to also strip the triangle markers:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_pdf_layout.py -v`
Expected: PASS (new triangle tests plus all existing WSJ-marker tests).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/pdf.py tests/test_pdf_layout.py
git commit -m "feat: stitch Bloomberg cross-page articles via solid triangle markers"
```

---

## Task 9: Full suite + Bloomberg/Economist end-to-end validation

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `./.venv/bin/python -m pytest tests/ -q`
Expected: all tests pass. Fix any regression before continuing.

- [ ] **Step 2: Validate Economist USA routing locally**

The new filename is the same Calibre e-edition, so detection must still route it to the edition parser. Copy the sample to the new name and inspect:

```bash
cp "/Users/pzk/workspace/NewspaperTranslator/TE-2026-06-13-PDF_WEB.pdf" \
   "/tmp/The Economist USA - June 20 2026.pdf"
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage phase3-parse-economist-pdf \
  --pdf-path "/tmp/The Economist USA - June 20 2026.pdf" | head -40
```

Expected: parses as Economist articles (the local edition path), not an error. If the CLI prints articles, routing is confirmed.

- [ ] **Step 3: Validate Bloomberg through MinerU (live)**

This requires the MinerU API path (network + credentials per `.env`). Run the document-processing path against the Bloomberg sample and confirm: (a) `source_name = 彭博商业周刊` and `publication_date = 2026-06-01`; (b) the merged debug markdown contains `►`/`◄` glyphs; (c) at least one cross-page article was stitched; (d) `article_images` has rows and a hero image is selected.

```bash
# Inspect the merged MinerU debug markdown for surviving markers after a parse run.
# (Use the project's existing document-processing entry; confirm the exact manage
#  subcommand with: PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage --help)
grep -c "►\|◄" <merged_debug_markdown_path>
```

**If the glyphs did NOT survive MinerU extraction:** capture how MinerU rendered the continuation (different glyph, HTML entity, or dropped). Update `_CONTINUED_TO_TRIANGLE` / `_CONTINUED_FROM_TRIANGLE` in `pdf.py` to match the observed token, re-run Task 8 tests, and re-validate. Do not mark this task complete until stitching is confirmed against real MinerU output.

- [ ] **Step 4: Commit any marker-regex adjustment from Step 3 (if needed)**

```bash
git add src/newspaper_translator/pdf.py tests/test_pdf_layout.py
git commit -m "fix: match Bloomberg continuation markers as emitted by MinerU"
```

---

## Self-Review Notes

- **Spec coverage:** filename source name (Tasks 1,3), filename date forms (Task 2), issue_date column/index (Task 4), issue-level dedupe (Tasks 5,6), publication-date alignment (Task 7), `►`/`◄` stitching with `▷` exclusion (Task 8), Economist routing + Bloomberg MinerU + hero image validation (Task 9). Image flow is verified, not re-implemented, per the spec's "no new image logic."
- **Validation risk** (markers surviving MinerU) is explicitly handled in Task 9 Step 3 with a concrete fallback.
- **Type consistency:** `extract_filename_date` / `match_publisher_alias` signatures are identical across Tasks 1, 2, 3, 5; `StoredDocument.issue_date` and the `issue_date` kwarg are consistent across Task 7; marker regex names `_CONTINUED_TO_TRIANGLE` / `_CONTINUED_FROM_TRIANGLE` are consistent across Task 8 and Task 9.
