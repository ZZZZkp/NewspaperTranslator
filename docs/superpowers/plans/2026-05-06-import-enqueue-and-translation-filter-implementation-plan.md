# Import Enqueue Fix and Translation-Prefix Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip Gmail PDFs whose filename starts with `【译】`, and wire newly imported documents into `document_processing_runs` so the worker can pick them up. Remove the dead `processing_tasks` table and its supporting Python module.

**Architecture:** Two surgical changes at the Gmail import boundary in `src/newspaper_translator/ingestion.py`. (A) Extend `_is_translated_pdf_filename` with a `【译】` prefix check on the basename; both call sites (attachment branch and body-link branch) already share this helper. (B) Replace the legacy `INSERT INTO processing_tasks` block in `import_gmail_pdf_attachment` with a call to the existing `create_document_processing_run`. Delete the no-longer-used `tasks.py`, `test_tasks.py`, and add a SQL migration that drops the `processing_tasks` table.

**Tech Stack:** Python 3, SQLite, `unittest`, sequential SQL migrations under `src/newspaper_translator/migrations/`.

**Spec:** `docs/superpowers/specs/2026-05-06-import-enqueue-and-translation-filter-design.md`

---

## File Map

**Modified:**
- `src/newspaper_translator/ingestion.py` — add `【译】` prefix to translation filter; switch enqueue from `processing_tasks` to `create_document_processing_run`; drop import of `tasks.ProcessingTask` and the `create_document_processing_task` helper
- `tests/test_ingestion.py` — drop tests for the removed helper; flip table assertions from `processing_tasks` to `document_processing_runs`; extend translated-variant integration test with `【译】` filename
- `tests/test_gmail.py` — extend body-link translated-filename test (or add a sibling test) covering `【译】xxx.pdf`
- `tests/test_database.py` — replace `assertIn("processing_tasks", table_names)` with `assertNotIn(...)` to prevent regression

**Created:**
- `src/newspaper_translator/migrations/0011_drop_processing_tasks.sql` — `DROP TABLE IF EXISTS processing_tasks;`

**Deleted:**
- `src/newspaper_translator/tasks.py`
- `tests/test_tasks.py`

---

## Pre-flight

- [ ] **Step 0a: Confirm baseline tests pass on `main`**

```bash
cd /Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator
./.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5
```

Expected: `OK` (no failures, no errors). If tests already fail unrelated to this change, stop and surface it before continuing.

- [ ] **Step 0b: Confirm `document_processing.create_document_processing_run` exists and signature matches plan**

```bash
grep -n "^def create_document_processing_run" src/newspaper_translator/document_processing.py
```

Expected: one line, `def create_document_processing_run(`. Then check the call signature accepts `database_url=` and `document_key=` kwargs (the implementation already lives at `document_processing.py:191`).

---

## Task 1: Add `【译】` prefix to the translation-filename filter

**Files:**
- Modify: `src/newspaper_translator/ingestion.py:10-14, 192-194`
- Test: `tests/test_ingestion.py` (add new unit tests; extend the existing integration test at line 311)

- [ ] **Step 1.1: Add failing unit tests for `GmailAttachment.is_pdf` covering the `【译】` prefix**

Append the following test class to `tests/test_ingestion.py` immediately before the `if __name__ == "__main__":` block (around line 365):

```python
class TranslationPrefixFilterTests(unittest.TestCase):
    def _attachment(self, filename: str) -> "GmailAttachment":
        self.assertIsNotNone(
            GmailAttachment,
            "GmailAttachment should be importable from newspaper_translator.ingestion",
        )
        return GmailAttachment(
            attachment_id="attachment-1",
            filename=filename,
            mime_type="application/pdf",
        )

    def test_rejects_pdf_whose_basename_starts_with_translation_prefix(self) -> None:
        for filename in (
            "【译】金融时报-5-5.pdf",
            "【译】华尔街日报-5-2.pdf",
            "【译】纽约时报.pdf",
            "/some/path/【译】xxx.pdf",
        ):
            with self.subTest(filename=filename):
                self.assertFalse(self._attachment(filename).is_pdf)

    def test_accepts_pdf_without_translation_prefix(self) -> None:
        for filename in (
            "金融时报-5-5.pdf",
            "华尔街日报-5-2.pdf",
            "wsj-2026-05-03.pdf",
        ):
            with self.subTest(filename=filename):
                self.assertTrue(self._attachment(filename).is_pdf)

    def test_keeps_legacy_translated_substring_patterns(self) -> None:
        for filename in (
            "中文-华尔街日报-2026-05-03.pdf",
            "中文-金融时报-2026-05-03.pdf",
            "【译】the_economist_(web_edition)_0205.pdf",
        ):
            with self.subTest(filename=filename):
                self.assertFalse(self._attachment(filename).is_pdf)
```

- [ ] **Step 1.2: Run the new tests and confirm the prefix tests fail**

```bash
./.venv/bin/python -m unittest tests.test_ingestion.TranslationPrefixFilterTests -v
```

Expected: `test_accepts_pdf_without_translation_prefix` and `test_keeps_legacy_translated_substring_patterns` PASS; `test_rejects_pdf_whose_basename_starts_with_translation_prefix` FAILS for the four `【译】xxx.pdf` cases (legacy code lacks the prefix rule).

- [ ] **Step 1.3: Implement the prefix rule in `ingestion.py`**

Edit `src/newspaper_translator/ingestion.py`:

Replace lines 10-14:

```python
TRANSLATED_FILENAME_PATTERNS = (
    "中文-华尔街日报",
    "中文-金融时报",
    "【译】the_economist_(web_edition)_0205.pdf",
)
```

With:

```python
TRANSLATION_PREFIXES = ("【译】",)
TRANSLATED_FILENAME_PATTERNS = (
    "中文-华尔街日报",
    "中文-金融时报",
    "【译】the_economist_(web_edition)_0205.pdf",
)
```

Replace the existing `_is_translated_pdf_filename` (lines 192-194):

```python
def _is_translated_pdf_filename(filename: str) -> bool:
    lowered_filename = filename.lower()
    return any(pattern in lowered_filename for pattern in TRANSLATED_FILENAME_PATTERNS)
```

With:

```python
def _is_translated_pdf_filename(filename: str) -> bool:
    base = Path(filename).name
    if base.startswith(TRANSLATION_PREFIXES):
        return True
    lowered_base = base.lower()
    return any(pattern in lowered_base for pattern in TRANSLATED_FILENAME_PATTERNS)
```

(`Path` is already imported at the top of the file from `from pathlib import Path`.)

- [ ] **Step 1.4: Re-run the unit tests and confirm all pass**

```bash
./.venv/bin/python -m unittest tests.test_ingestion.TranslationPrefixFilterTests -v
```

Expected: 3 tests pass.

- [ ] **Step 1.5: Extend the existing integration test for `【译】` coverage**

In `tests/test_ingestion.py`, find `test_import_selected_messages_skips_known_translated_pdf_variants` (around line 311) and extend its `attachments` list to include a `【译】` variant. Locate this existing block:

```python
attachments=[
    GmailAttachment(
        attachment_id="attachment-1",
        filename="wsj-2026-05-03.pdf",
        mime_type="application/pdf",
        content_bytes=b"%PDF-1.7 english",
    ),
    GmailAttachment(
        attachment_id="attachment-2",
        filename="中文-华尔街日报-2026-05-03.pdf",
        mime_type="application/pdf",
        content_bytes=b"%PDF-1.7 translated",
    ),
],
```

Add a third attachment with the new prefix variant:

```python
attachments=[
    GmailAttachment(
        attachment_id="attachment-1",
        filename="wsj-2026-05-03.pdf",
        mime_type="application/pdf",
        content_bytes=b"%PDF-1.7 english",
    ),
    GmailAttachment(
        attachment_id="attachment-2",
        filename="中文-华尔街日报-2026-05-03.pdf",
        mime_type="application/pdf",
        content_bytes=b"%PDF-1.7 translated",
    ),
    GmailAttachment(
        attachment_id="attachment-3",
        filename="【译】金融时报-5-5.pdf",
        mime_type="application/pdf",
        content_bytes=b"%PDF-1.7 prefix-translated",
    ),
],
```

The existing assertion `self.assertEqual(stored_filenames, [("wsj-2026-05-03.pdf",)])` still expresses the right outcome — the `【译】` and `中文-` attachments are both filtered.

- [ ] **Step 1.6: Run the integration test and the rest of the file**

```bash
./.venv/bin/python -m unittest tests.test_ingestion -v
```

Expected: all tests in `tests/test_ingestion.py` PASS.

- [ ] **Step 1.7: Commit**

```bash
git add src/newspaper_translator/ingestion.py tests/test_ingestion.py
git commit -m "$(cat <<'EOF'
Skip 【译】-prefixed PDFs in Gmail attachment filter

Adds a basename startswith check for the 【译】 translation prefix on
top of the existing legacy substring patterns, so files like
【译】金融时报-5-5.pdf are no longer downloaded into raw storage.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Cover the body-link path with a `【译】` prefix test

**Files:**
- Test: `tests/test_gmail.py` (extend the existing translated-body-link test or add a sibling)

The body-link branch (`src/newspaper_translator/gmail.py:567`) already calls the same `_is_translated_pdf_filename`-equivalent check via `TRANSLATED_FILENAME_PATTERNS` — but after Task 1, the production code path imports the helper instead. We need to verify the body-link path also picks up the new prefix rule, since this is a separate code site from `GmailAttachment.is_pdf`.

- [ ] **Step 2.1: Inspect the current body-link test fixture**

```bash
grep -n "_FakeTranslatedBodyLinkService\|translated_url\|body_link_filename_filtered" tests/test_gmail.py | head -20
```

Use this to confirm the fake `_FakeTranslatedBodyLink*` classes (around line 1670+) and the test at `test_skips_translated_pdf_body_links_and_records_filtered_audit_items` (line 710).

- [ ] **Step 2.2: Add a failing sibling test for the `【译】` prefix on the body-link path**

Find the existing test at `tests/test_gmail.py:710`. Immediately after it (before the next `def test_*`), add a new test using a `【译】` filename. The new test mirrors the existing one but with a different `translated_url`:

```python
    def test_skips_translation_prefix_pdf_body_links_and_records_filtered_audit_items(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(list_import_run_items)

        translated_url = "https://example.com/pdfs/【译】金融时报-5-5.pdf"
        regular_url = "https://example.com/pdfs/regular-paper.pdf"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["example.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeTranslatedBodyLinkService(translated_url, regular_url),
                downloader=_FakeTranslatedBodyLinkDownloader(translated_url, regular_url),
            )

            skipped_items = list_import_run_items(
                database_url=database_url,
                run_id=summary.run_id,
                status="skipped",
            )

        self.assertEqual(summary.imported_attachment_count, 1)
        self.assertEqual(summary.created_document_count, 1)
        filtered_items = [
            item for item in skipped_items
            if item.detail_code == "body_link_filename_filtered"
        ]
        self.assertEqual(len(filtered_items), 1)
        self.assertEqual(filtered_items[0].link_url, translated_url)
```

The shared `_FakeTranslatedBodyLink*` classes route any URL the test passes to a `%PDF-1.7 ...` payload whose downloaded filename equals the URL's basename — so passing `【译】金融时报-5-5.pdf` in the URL yields an attachment with that filename, which the production code must reject.

- [ ] **Step 2.3: Run and confirm the new test passes**

```bash
./.venv/bin/python -m unittest tests.test_gmail.GmailImportTests.test_skips_translation_prefix_pdf_body_links_and_records_filtered_audit_items -v
```

(Replace `GmailImportTests` with the actual class name of the surrounding test class — confirm via `grep -n "class .*:" tests/test_gmail.py | head` if needed.)

Expected: PASS. (Production code already shares the new prefix rule via `TRANSLATED_FILENAME_PATTERNS` and the prefix tuple in `ingestion.py`. If FAIL, the body-link branch is not calling the shared helper — fix `gmail.py:566-567` to call `_is_translated_pdf_filename` from `ingestion` instead of inlining the substring check, then re-run.)

If the test failed in the way above, apply this fix to `src/newspaper_translator/gmail.py` around line 566-567:

Replace:

```python
            if attachment is not None:
                lowered_filename = attachment.filename.lower()
                if any(pattern in lowered_filename for pattern in TRANSLATED_FILENAME_PATTERNS):
```

With (importing `_is_translated_pdf_filename` near the existing `from newspaper_translator.ingestion import ...` statement at the top of `gmail.py`):

```python
            if attachment is not None:
                if _is_translated_pdf_filename(attachment.filename):
```

Then re-run Step 2.3.

- [ ] **Step 2.4: Run all `test_gmail.py` to ensure no regressions**

```bash
./.venv/bin/python -m unittest tests.test_gmail -v 2>&1 | tail -10
```

Expected: `OK`.

- [ ] **Step 2.5: Commit**

```bash
git add tests/test_gmail.py src/newspaper_translator/gmail.py
git commit -m "$(cat <<'EOF'
Cover 【译】-prefixed body-link PDFs in skip filter

Mirrors the existing 中文- body-link skip test for the 【译】 prefix
introduced in the previous commit, exercising the shared
_is_translated_pdf_filename helper.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

(If you did not need to modify `gmail.py`, drop it from the `git add` line.)

---

## Task 3: Wire `import_gmail_pdf_attachment` into `document_processing_runs`

**Files:**
- Modify: `src/newspaper_translator/ingestion.py:1-10, 60-61, 121-144`
- Test: `tests/test_ingestion.py:13-30, 89-98, 153-184, 220-243`

- [ ] **Step 3.1: Update `tests/test_ingestion.py` to expect `document_processing_runs` rows**

In `tests/test_ingestion.py`, three test-related changes happen together:

(a) Replace the import block at lines 13-30:

```python
try:
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.ingestion import (
        GmailAttachment,
        GmailMessage,
        create_document_processing_task,
        import_selected_messages,
        import_gmail_pdf_attachment,
        select_target_messages,
    )
except ImportError:
    run_pending_migrations = None
    GmailAttachment = None
    GmailMessage = None
    create_document_processing_task = None
    import_selected_messages = None
    import_gmail_pdf_attachment = None
    select_target_messages = None
```

With:

```python
try:
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.ingestion import (
        GmailAttachment,
        GmailMessage,
        import_selected_messages,
        import_gmail_pdf_attachment,
        select_target_messages,
    )
except ImportError:
    run_pending_migrations = None
    GmailAttachment = None
    GmailMessage = None
    import_selected_messages = None
    import_gmail_pdf_attachment = None
    select_target_messages = None
```

(b) Delete the entire `test_creates_a_pending_document_processing_task_after_a_successful_import` method (lines 89-98 in the unmodified file). Tests should no longer reference `create_document_processing_task`.

(c) In `test_imports_a_pdf_attachment_into_raw_storage_and_document_metadata` (around lines 100-184), replace the `stored_task` query and assertion. Find:

```python
                stored_task = connection.execute(
                    """
                    SELECT task_name, status
                    FROM processing_tasks
                    WHERE task_name = ?
                    """,
                    (f"process-document:{result.document_key}",),
                ).fetchone()
```

Replace with:

```python
                stored_processing_run = connection.execute(
                    """
                    SELECT document_key, status, current_step
                    FROM document_processing_runs
                    WHERE document_key = ?
                    """,
                    (result.document_key,),
                ).fetchone()
```

And replace the trailing assertion:

```python
        self.assertEqual(
            stored_task,
            (f"process-document:{result.document_key}", "pending"),
        )
```

With:

```python
        self.assertEqual(
            stored_processing_run,
            (result.document_key, "pending", "parse_persist"),
        )
```

(d) In `test_skips_duplicate_pdf_imports_for_the_same_attachment_payload` (around lines 186-243), replace:

```python
                task_count = connection.execute(
                    "SELECT COUNT(*) FROM processing_tasks"
                ).fetchone()[0]
```

With:

```python
                processing_run_count = connection.execute(
                    "SELECT COUNT(*) FROM document_processing_runs"
                ).fetchone()[0]
```

And replace the trailing assertion:

```python
        self.assertEqual(task_count, 1)
```

With:

```python
        self.assertEqual(processing_run_count, 1)
```

- [ ] **Step 3.2: Run `test_ingestion.py` and confirm the new assertions fail**

```bash
./.venv/bin/python -m unittest tests.test_ingestion -v 2>&1 | tail -20
```

Expected: `test_imports_a_pdf_attachment_into_raw_storage_and_document_metadata` and `test_skips_duplicate_pdf_imports_for_the_same_attachment_payload` FAIL because `document_processing_runs` is empty (production code still writes `processing_tasks`).

- [ ] **Step 3.3: Switch `import_gmail_pdf_attachment` to write `document_processing_runs`**

Edit `src/newspaper_translator/ingestion.py`:

(a) Replace the import block at lines 1-8:

```python
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3

from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.documents import DocumentIdentity
from newspaper_translator.tasks import ProcessingTask
```

With:

```python
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3

from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.document_processing import create_document_processing_run
from newspaper_translator.documents import DocumentIdentity
```

(b) Delete the helper at lines 60-62:

```python
def create_document_processing_task(*, document_key: str) -> ProcessingTask:
    return ProcessingTask.create(task_name=f"process-document:{document_key}")
```

(c) Replace the body of `import_gmail_pdf_attachment` (lines 121-144) starting from `was_created = cursor.rowcount == 1`:

```python
        was_created = cursor.rowcount == 1

        if was_created and not raw_path.exists():
            raw_path.write_bytes(attachment.content_bytes)

        if was_created:
            task = create_document_processing_task(document_key=identity.document_key)
            connection.execute(
                """
                INSERT OR IGNORE INTO processing_tasks (task_name, status)
                VALUES (?, ?)
                """,
                (task.task_name, task.status),
            )

        connection.commit()
        return ImportedDocument(
            document_key=identity.document_key,
            content_hash=content_hash,
            raw_path=raw_path,
            was_created=was_created,
        )
    finally:
        connection.close()
```

With:

```python
        was_created = cursor.rowcount == 1

        if was_created and not raw_path.exists():
            raw_path.write_bytes(attachment.content_bytes)

        connection.commit()
    finally:
        connection.close()

    if was_created:
        create_document_processing_run(
            database_url=database_url,
            document_key=identity.document_key,
        )

    return ImportedDocument(
        document_key=identity.document_key,
        content_hash=content_hash,
        raw_path=raw_path,
        was_created=was_created,
    )
```

Rationale: the documents-table commit and the `create_document_processing_run` call now run on **separate connections** (the helper opens its own), so we close the first connection before invoking the helper. This guarantees the `documents` row is durably visible before the `pending` run is inserted.

- [ ] **Step 3.4: Run `test_ingestion.py` and confirm the rewritten tests pass**

```bash
./.venv/bin/python -m unittest tests.test_ingestion -v 2>&1 | tail -20
```

Expected: all tests in `tests/test_ingestion.py` PASS.

- [ ] **Step 3.5: Run the full suite to catch any other consumer of `processing_tasks` or `create_document_processing_task`**

```bash
./.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -10
```

Expected: `OK`. (`test_tasks.py` still passes because `tasks.py` still exists; cleanup happens in Task 5.)

- [ ] **Step 3.6: Commit**

```bash
git add src/newspaper_translator/ingestion.py tests/test_ingestion.py
git commit -m "$(cat <<'EOF'
Enqueue imported documents into document_processing_runs

Replaces the legacy processing_tasks insert in import_gmail_pdf_attachment
with a call to create_document_processing_run so the worker's processing
tick finds new documents on its next poll. Drops the now-unused
create_document_processing_task helper and its test.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Drop the `processing_tasks` table via migration 0011

**Files:**
- Create: `src/newspaper_translator/migrations/0011_drop_processing_tasks.sql`
- Modify: `tests/test_database.py:49-53`

- [ ] **Step 4.1: Update the migration test to reject the `processing_tasks` table**

Edit `tests/test_database.py` around line 49-53. Find:

```python
        self.assertIn("0001_initial", applied_versions)
        self.assertIn("schema_migrations", table_names)
        self.assertIn("documents", table_names)
        self.assertIn("processing_tasks", table_names)
        self.assertIn("0001_initial", recorded_versions)
```

Replace with:

```python
        self.assertIn("0001_initial", applied_versions)
        self.assertIn("schema_migrations", table_names)
        self.assertIn("documents", table_names)
        self.assertNotIn("processing_tasks", table_names)
        self.assertIn("0001_initial", recorded_versions)
```

- [ ] **Step 4.2: Run the migration test and confirm it fails**

```bash
./.venv/bin/python -m unittest tests.test_database -v 2>&1 | tail -10
```

Expected: at least one test FAIL — `processing_tasks` still exists after running migrations 0001-0010.

- [ ] **Step 4.3: Add the new migration**

Create `src/newspaper_translator/migrations/0011_drop_processing_tasks.sql` with:

```sql
DROP TABLE IF EXISTS processing_tasks;
```

- [ ] **Step 4.4: Re-run the migration test**

```bash
./.venv/bin/python -m unittest tests.test_database -v 2>&1 | tail -10
```

Expected: `OK`.

- [ ] **Step 4.5: Commit**

```bash
git add src/newspaper_translator/migrations/0011_drop_processing_tasks.sql tests/test_database.py
git commit -m "$(cat <<'EOF'
Drop processing_tasks table in migration 0011

Removes the legacy processing_tasks table from the schema now that no
production code reads or writes it. The test_database migration test is
flipped to assert the table is absent so a future reintroduction fails
loudly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Delete `tasks.py` and `test_tasks.py`

**Files:**
- Delete: `src/newspaper_translator/tasks.py`
- Delete: `tests/test_tasks.py`

- [ ] **Step 5.1: Confirm no remaining references**

```bash
grep -rn "newspaper_translator.tasks\|ProcessingTask\|InvalidTaskTransitionError" \
    src/ tests/ 2>/dev/null | grep -v __pycache__
```

Expected: only matches inside `src/newspaper_translator/tasks.py` and `tests/test_tasks.py` themselves. If any other file still references these symbols, fix that first before proceeding.

- [ ] **Step 5.2: Delete the files**

```bash
git rm src/newspaper_translator/tasks.py tests/test_tasks.py
```

- [ ] **Step 5.3: Run the full test suite**

```bash
./.venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -10
```

Expected: `OK`. No `ImportError`, no `ModuleNotFoundError`.

- [ ] **Step 5.4: Commit**

```bash
git commit -m "$(cat <<'EOF'
Delete unused tasks module and its tests

The processing_tasks table and its supporting ProcessingTask dataclass
have no remaining consumers after the import path moved to
document_processing_runs. Removing the dead module keeps the package
focused on the active processing pipeline.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: End-to-end verification in the running Docker stack

**Files:** none (operational verification of the deployed change).

- [ ] **Step 6.1: Rebuild and restart the affected services**

```bash
docker compose up -d --build web worker
```

Expected: both services come up healthy. (`docker compose ps` should show `Up (healthy)` for `web` and `worker` within a minute.)

- [ ] **Step 6.2: Confirm migration 0011 ran inside the container**

```bash
docker exec newspapertranslator-worker-1 python -c "
import sqlite3
c = sqlite3.connect('/data/newspaper-translator.db')
tables = {r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()}
print('processing_tasks present:', 'processing_tasks' in tables)
print('schema_migrations recorded:', [r[0] for r in c.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()])
"
```

Expected: `processing_tasks present: False`. The migration list ends with `0011_drop_processing_tasks`.

- [ ] **Step 6.3: Trigger a manual import from the frontend or via curl**

```bash
curl -X POST http://localhost:${WEB_PORT:-8000}/api/gmail/import
```

Expected: HTTP 200 with `{"import_run": {...}}`. The response includes `created_document_count` for any newly imported PDFs and `imported_attachment_count` for new + previously seen.

- [ ] **Step 6.4: Verify any `【译】` files were skipped and that real PDFs were enqueued**

```bash
docker exec newspapertranslator-worker-1 python -c "
import sqlite3
c = sqlite3.connect('/data/newspaper-translator.db')
print('documents with 【译】 prefix:', c.execute(\"SELECT COUNT(*) FROM documents WHERE original_filename LIKE '【译】%'\").fetchone()[0])
print('document_processing_runs by status:')
for row in c.execute('SELECT status, COUNT(*) FROM document_processing_runs GROUP BY status'):
    print(' ', row)
print('most recent runs:')
for r in c.execute('SELECT substr(document_key,-30), status, current_step, last_attempt_started_at FROM document_processing_runs ORDER BY created_at DESC LIMIT 5'):
    print(' ', r)
"
```

Expected:
- `documents with 【译】 prefix: 0` for any documents created **after** the rebuild (existing rows from before this change may still be there — that is expected and not a regression).
- `document_processing_runs` contains a `pending` row for every newly created document.

- [ ] **Step 6.5: Watch the next worker tick claim the new pending rows**

```bash
docker logs --since 60s -f newspapertranslator-worker-1 2>&1 | grep --line-buffered -E '"selected_document_count": [1-9]|document\.claimed|scheduler\.processing\.finished'
```

Expected within ~60-90 seconds: a `scheduler.processing.started` event, one or more `document.claimed` events for the freshly enqueued documents, then a `scheduler.processing.finished` event with `selected_document_count >= 1`. Stop the tail with Ctrl-C.

- [ ] **Step 6.6: Final spot check — no orphaned documents**

```bash
docker exec newspapertranslator-worker-1 python -c "
import sqlite3
c = sqlite3.connect('/data/newspaper-translator.db')
orphans = c.execute('''
    SELECT COUNT(*) FROM documents d
    LEFT JOIN document_processing_runs r ON r.document_key = d.document_key
    WHERE r.processing_run_id IS NULL
''').fetchone()[0]
print('documents without a processing run:', orphans)
"
```

Expected: `0`. (If non-zero, those are pre-existing orphans from before this change; record the count and decide whether to backfill manually as a follow-up — the new code prevents fresh orphans but does not heal historical ones.)

---

## Self-review checklist (executed during plan authoring)

- [x] Spec section "Translation-prefix filter (change A)" → Task 1 + Task 2.
- [x] Spec section "Enqueue at import time (change B, core)" → Task 3.
- [x] Spec section "Dead-code cleanup" → Task 3 (test edits + helper removal) + Task 5 (file deletions).
- [x] Spec section "Database migration" → Task 4.
- [x] Spec section "Tests" → covered across Tasks 1, 2, 3, 4 (every new and adjusted test enumerated above).
- [x] Spec section "End-to-end flow after changes" → Task 6 verifies the flow against the running container.
- [x] No `TBD` / `TODO` / "implement later" anywhere.
- [x] Type and method names consistent: `create_document_processing_run(database_url=, document_key=)` matches the existing signature in `document_processing.py:191`. `_is_translated_pdf_filename` keeps its name across both call sites. `TRANSLATION_PREFIXES` is a tuple to allow `str.startswith(tuple)`.
- [x] Each task's tests fail first (where applicable) and the implementation step shows the exact code.
