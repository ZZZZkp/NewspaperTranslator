# Import enqueue fix and translation-prefix filter

Date: 2026-05-06
Status: design approved, ready for implementation plan

## Background

Two issues surfaced together when verifying the manual Gmail import flow in the local Docker stack on 2026-05-06:

1. PDFs imported through the manual `/api/gmail/import` endpoint (and by extension the scheduled Gmail import) were never picked up by the worker for downstream processing. The worker polled every 60 seconds and consistently reported `selected_document_count: 0` even with 22 freshly imported documents in the database.
2. Translated Chinese PDFs with the `【译】` prefix (for example `【译】金融时报-5-5.pdf`, `【译】华尔街日报-5-2.pdf`) were still being downloaded into raw storage, even though there is already a "skip translated PDFs" filter in the codebase.

Both issues live at the same boundary: the moment the Gmail importer decides what to do with a freshly fetched attachment.

## Root causes

### Enqueue chain is broken

`src/newspaper_translator/ingestion.py:127` writes a row into the legacy `processing_tasks` table after a new document is imported, via `create_document_processing_task`. Nothing in the codebase consumes the `processing_tasks` table any more.

The worker's processing tick (`src/newspaper_translator/document_processing.py:1531 run_processing_tick`) only consults `document_processing_runs` through `list_eligible_document_processing_runs` (`document_processing.py:520`). The only insert into `document_processing_runs` is `create_document_processing_run` (`document_processing.py:191`), and its sole caller is `process_document` itself (`document_processing.py:1078`) — which is only invoked for document keys already returned by `list_eligible_document_processing_runs`.

Result: there is no path from "new document imported" to "document_processing_runs row exists." The chicken-and-egg means new documents never enter the queue.

The current production database confirms this: 25 documents imported, 22 pending rows in the dead `processing_tasks` table, only 3 historical rows in `document_processing_runs` (all from 2026-04-29 / 2026-04-30, before the manual-import work landed).

### Translation filter is too narrow

`src/newspaper_translator/ingestion.py:10-14` defines:

```python
TRANSLATED_FILENAME_PATTERNS = (
    "中文-华尔街日报",
    "中文-金融时报",
    "【译】the_economist_(web_edition)_0205.pdf",
)
```

`_is_translated_pdf_filename` checks whether any pattern is a case-folded substring of the filename. The third entry is pinned to one specific filename. Files like `【译】金融时报-5-5.pdf` and `【译】华尔街日报-5-2.pdf` do not match any pattern and slip through.

## Goals

- New documents created by `import_gmail_pdf_attachment` are immediately eligible for the worker's processing tick.
- The legacy `processing_tasks` table and its supporting code are removed cleanly.
- Filenames beginning with `【译】` are recognized as translated variants and skipped at import time, in both the attachment path and the body-link path.
- Existing tests pass; new tests cover the additional behaviors.

## Non-goals

- No discovery / self-healing tick that scans for orphan documents. Once the import path enqueues correctly, there is no orphan source.
- No change to the worker scheduler cadence, concurrency, or step-retry semantics.
- No change to MinerU / Gemini configuration, the article processing pipeline, or the dashboard surfaces.
- No backfill script for the historical orphan documents — those were already manually backfilled into `document_processing_runs` during incident triage on 2026-05-06.

## Design

### Translation-prefix filter (change A)

`src/newspaper_translator/ingestion.py` — replace `_is_translated_pdf_filename`:

```python
TRANSLATION_PREFIXES = ("【译】",)
TRANSLATED_FILENAME_PATTERNS = (   # legacy substring patterns, unchanged
    "中文-华尔街日报",
    "中文-金融时报",
    "【译】the_economist_(web_edition)_0205.pdf",
)

def _is_translated_pdf_filename(filename: str) -> bool:
    base = Path(filename).name
    if base.startswith(TRANSLATION_PREFIXES):
        return True
    lowered = base.lower()
    return any(pattern in lowered for pattern in TRANSLATED_FILENAME_PATTERNS)
```

Notes:

- `Path(filename).name` strips any directory component so a body-link URL whose path happens to contain `【译】` cannot misclassify a non-translated final filename. The base-name normalization applies symmetrically to the legacy substring check.
- The prefix tuple uses `str.startswith` with a tuple argument, which evaluates each prefix in order. CJK characters have no case, so no `lower()` is applied before the prefix check.
- The legacy substring list is preserved verbatim so existing behavior is not lost.
- Both call sites already share this function: `GmailAttachment.is_pdf` (`ingestion.py:25-29`) and the body-link branch (`gmail.py:566-576`). Neither call site changes.

### Enqueue at import time (change B, core)

`src/newspaper_translator/ingestion.py` — `import_gmail_pdf_attachment`:

1. Remove `from newspaper_translator.tasks import ProcessingTask`.
2. Add `from newspaper_translator.document_processing import create_document_processing_run`. (Verified: `document_processing.py` does not import `ingestion.py`, so this is one-directional.)
3. Delete the `create_document_processing_task` helper (lines 60-61).
4. In the body of `import_gmail_pdf_attachment`, replace the `if was_created: ... INSERT INTO processing_tasks ...` block with:
   - Commit the existing `documents` insert first (move the existing trailing `connection.commit()` up to right after the `documents` write and the `raw_path.write_bytes(...)` call).
   - After the commit, if `was_created`, call `create_document_processing_run(database_url=database_url, document_key=identity.document_key)`.

   Sequencing rationale: `create_document_processing_run` opens its own SQLite connection and commits independently. Committing the `documents` row first ensures there is never a transient state where a `pending` processing run references a `document_key` not yet visible to other readers.

   Idempotency rationale: `create_document_processing_run` already uses `INSERT OR IGNORE`, and `was_created` is only true on the first successful insert into `documents`, so retries cannot double-enqueue.

### Dead-code cleanup

Files to delete:

- `src/newspaper_translator/tasks.py`
- `tests/test_tasks.py`

Files to modify:

- `tests/test_ingestion.py`:
  - Remove the `from newspaper_translator.ingestion import ... create_document_processing_task` import and its `except ImportError` placeholder (lines 18-27).
  - Delete `test_create_document_processing_task_*` (around line 91-95).
  - Replace the two assertions that count rows in `processing_tasks` (around lines 155-156 and 232-233) with assertions that read `document_processing_runs` for the imported document key and confirm a `pending` row exists.
- `tests/test_database.py:52`: remove the `assertIn("processing_tasks", table_names)` line; add an `assertNotIn("processing_tasks", table_names)` to guard against accidental reintroduction.

### Database migration

New file `src/newspaper_translator/migrations/0011_drop_processing_tasks.sql`:

```sql
DROP TABLE IF EXISTS processing_tasks;
```

The migration runner already executes files in lexicographic order. Existing SQLite deployments will drop the legacy table on the next `migrate` invocation. The container healthcheck and worker startup both run migrations, so no manual step is required after deploy.

### Tests

New tests:

- `tests/test_ingestion.py`:
  - `_is_translated_pdf_filename` accepts `【译】金融时报-5-5.pdf`, `【译】华尔街日报-5-2.pdf`, `【译】纽约时报.pdf`, and a path-prefixed `/some/dir/【译】xxx.pdf`.
  - `_is_translated_pdf_filename` rejects `金融时报-5-5.pdf` (no prefix) and `华尔街日报-5-2.pdf`.
  - `import_gmail_pdf_attachment` writes a `pending` row into `document_processing_runs` for newly created documents, and does not write a duplicate row when the same attachment is imported twice.
- `tests/test_gmail.py`:
  - The body-link branch skips a resolved `【译】xxx.pdf` filename and emits a `body_link_filename_filtered` audit item, mirroring the existing `中文-` test.

Existing tests adjusted:

- `tests/test_ingestion.py` row-count assertions move from `processing_tasks` to `document_processing_runs`.
- `tests/test_database.py` migration table assertion flips from "expects" to "rejects" `processing_tasks`.

### End-to-end flow after changes

```
frontend "立即拉取邮件"
  └─ POST /api/gmail/import  (web)
     └─ import_from_gmail()
        └─ import_gmail_pdf_attachment()
           ├─ skip if _is_translated_pdf_filename(...)
           ├─ INSERT OR IGNORE INTO documents  ──┐
           │                                     ├─ committed together
           ├─ raw_path.write_bytes(...)  ────────┘
           └─ create_document_processing_run()   ← new
              └─ INSERT OR IGNORE INTO document_processing_runs (pending)

worker tick (every PROCESSING_POLL_INTERVAL_SECONDS, default 60s)
  └─ list_eligible_document_processing_runs()    ← sees new pending rows
     └─ process_document() → parse_persist → enrich
```

## Out-of-scope follow-ups

- A discovery / self-healing tick (the previously discussed Option 2) is intentionally not part of this design. If a future ingestion source is added that does not flow through `import_gmail_pdf_attachment`, the right fix is to apply the same enqueue call at that new entry point rather than re-add a global scanner.
- The `processing_tasks` data preserved in the live database from before this change is dropped by the migration; no separate backfill is needed.
