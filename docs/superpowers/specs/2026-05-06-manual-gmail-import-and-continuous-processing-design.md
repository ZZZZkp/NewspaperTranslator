# Manual Gmail Import And Continuous Processing Design

Date: 2026-05-06

Related documents:

- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)
- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)
- [Article Processing Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-02-article-processing-workbench-design.md)
- [Gmail Body-Link Download Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-03-gmail-body-link-download-design.md)

## Overview

The current worker couples Gmail import and downstream document/article processing inside one scheduler tick. By default, that tick runs every 2 hours. This means pending document and article tasks wait for the same 2-hour cadence as Gmail fetching, even when they are already queued.

This design separates those concerns:

- Gmail import remains a timed ingestion activity, defaulting to every 2 hours.
- Document and article processing become a continuous queue consumer, defaulting to every 60 seconds.
- The frontend operator workbench gains a manual "fetch latest mail" action that triggers Gmail import immediately.

The resulting product behavior is:

1. Operators can click one button to fetch the newest Gmail attachments and body-link PDFs into the task queue.
2. The worker automatically processes queued documents and articles without waiting for the next 2-hour Gmail interval.
3. Existing document/article retry, locking, stale recovery, and status semantics remain intact.

## Goals

- Add a frontend button in the operator workbench for manually fetching the latest Gmail attachments and body-link PDFs.
- Keep Gmail automatic import on a 2-hour best-effort interval.
- Make document and article processing run whenever eligible work exists, with a short polling interval.
- Preserve the current document-first, article-second processing order.
- Avoid overlapping processing ticks in one worker process.
- Keep database-level claim and lock behavior as the concurrency safety net.
- Reuse the existing Gmail import, document processing, and article processing services where practical.
- Keep the first implementation suitable for the existing single local Docker worker.

## Non-Goals

- Splitting the deployment into multiple worker containers.
- Replacing SQLite-backed task state with an external queue.
- Adding batch retry, cancellation, pause, priority, or alerting features.
- Changing MinerU, Gemini, parsing, enrichment, or article identity behavior.
- Guaranteeing instant processing while the host laptop is asleep.
- Redesigning the whole operator workbench layout.

## Product Decisions

The user-approved product decisions are:

- Use one worker process with separated import and processing loops.
- Keep Gmail import at the existing 2-hour cadence.
- Make document and article processing poll continuously, using a 60-second default.
- Put the manual Gmail fetch button at the top of the operator workbench.
- The button text should communicate an operator action such as "立即拉取邮件".
- Clicking the button should fetch Gmail only; processing is handled by the continuous processing loop.

## Recommended Architecture

Use a single `worker` process with two internal scheduling loops.

### Import Loop

The import loop is responsible only for Gmail ingestion.

Responsibilities:

- Run on `GMAIL_IMPORT_INTERVAL_SECONDS`, default `7200`.
- Preserve startup catch-up semantics: if the latest Gmail import is overdue, run once immediately.
- Call the existing Gmail import path with `GMAIL_CONFIG_PATH`, `STORAGE_ROOT`, and `DATABASE_URL`.
- Persist import audit state and imported documents through the existing ingestion path.
- Ensure newly imported documents have corresponding document-processing runs that can become eligible for processing.

The import loop must not run MinerU parsing or Gemini enrichment directly.

### Processing Loop

The processing loop is responsible for queued document and article work.

Responsibilities:

- Run on `PROCESSING_POLL_INTERVAL_SECONDS`, default `60`.
- Recover stale document and article runs on startup before normal processing starts.
- Select eligible document-processing runs.
- Process documents concurrently according to `DOCUMENT_WORKER_CONCURRENCY`.
- Select eligible article-processing runs after document processing has completed for that tick.
- Process articles concurrently according to `ARTICLE_WORKER_CONCURRENCY`.
- Avoid starting a second processing tick while the previous one is still running in the same worker process.

Within each processing tick, the order remains:

1. document processing
2. article processing

This order lets articles created by a document-processing pass be picked up either later in the same tick or in the next 60-second tick.

### Compatibility Boundary

The existing `scheduler-run-once` CLI should remain usable. It may keep its existing full-pipeline semantics by becoming a composition of:

1. `run_import_tick`
2. `run_processing_tick`

The implementation should introduce clearer function names such as `run_import_tick` and `run_processing_tick` so the code no longer depends on one mixed "scheduler tick" concept for both behaviors.

## Backend API

Add:

- `POST /api/gmail/import`

Behavior:

- Triggers the same Gmail import service used by the import loop.
- Does not wait for MinerU parsing, document processing, or article processing.
- Returns a JSON import summary.

Recommended response shape:

```json
{
  "import_run": {
    "run_id": "import-run-id",
    "status": "succeeded",
    "fetched_message_count": 25,
    "imported_attachment_count": 3,
    "created_document_count": 2,
    "skipped_document_count": 1
  }
}
```

If no new documents are found, the API still succeeds and returns `created_document_count: 0`.

If Gmail import fails, the API returns an error response and the import audit path records the failed run where the existing Gmail import behavior already supports it.

## Frontend Design

Add a manual Gmail import action to the top of the operator workbench.

Placement:

- In the shared operator workbench area, above or beside the document/article processing tabs.
- The action should be visible when operators are working in document or article processing views.

Behavior:

- Button label: `立即拉取邮件`.
- On click, disable the button and show a status message such as `正在拉取邮件...`.
- Call `POST /api/gmail/import`.
- On success:
  - show a concise summary, including created document count
  - refresh the document-processing list
  - leave article-processing refresh to the current view or refresh it if that view is active
- On failure:
  - show a concise error message
  - re-enable the button
  - do not overwrite current list content with a false success state

The frontend should not promise that parsing, translation, summaries, or tags are complete after the button returns. The correct message is that mail has been checked and background processing will pick up queued work.

## Synchronization And Concurrency

### Gmail Import Versus Processing

Gmail import and processing may overlap safely if the import path commits document state transactionally.

Rules:

- Processing only sees documents and processing runs that have already been committed.
- A document imported after a processing scan will be picked up by the next processing tick.
- Gmail deduplication remains responsible for avoiding duplicate documents across repeated imports.

### Document Processing Versus Article Processing

Document processing may create article-processing runs. Article processing must only consume article runs after article data and run records are durable.

Rules:

- `run_processing_tick` processes documents before articles.
- Article-processing runs become eligible only after the article persistence boundary is complete.
- Newly created article tasks may be handled in the same tick or in the next tick.

### Processing Tick Reentry

The worker should not start a new processing tick while one is still active in the same process.

Rules:

- The main loop tracks whether processing is already running.
- If processing takes longer than `PROCESSING_POLL_INTERVAL_SECONDS`, the next poll is skipped rather than overlapped.
- Existing database claim, `running` status, `locked_by`, `lock_expires_at`, and stale recovery remain the cross-process safety mechanism.

### Manual Import Reentry

The frontend disables the button while the request is active. The backend may also add a lightweight in-process guard to avoid two manual imports running concurrently in the same web process.

Repeated imports are safe because Gmail import already has dedupe behavior, but avoiding concurrent imports improves operator feedback and reduces duplicate remote work.

## Error Handling

### Gmail Import Failure

- API returns a non-2xx JSON error.
- Frontend shows a failure message.
- Existing pending document and article tasks continue to be processed by the worker.

### Gmail Import Finds Nothing New

- API returns success.
- Frontend shows that mail was checked and no new documents were created.
- Processing loop continues to consume existing queued work.

### Processing Failure

Processing failures keep the existing semantics:

- immediate step retries are applied where already configured
- failed document runs become retryable or terminal based on existing failure limits
- failed article runs use the existing article-processing retry and failure model
- stale recovery handles abandoned `running` work after interruption or sleep

## Configuration

Recommended settings:

- `GMAIL_IMPORT_INTERVAL_SECONDS=7200`
- `PROCESSING_POLL_INTERVAL_SECONDS=60`
- `DOCUMENT_WORKER_CONCURRENCY=2`
- `ARTICLE_WORKER_CONCURRENCY`, defaulting to document concurrency if unset
- existing `STEP_RETRY_LIMIT`
- existing lock timeout and stale recovery settings

The older `SCHEDULER_INTERVAL_SECONDS` may remain as a compatibility alias for the Gmail import interval during the transition.

## Testing

Backend coverage:

- Worker startup recovers stale document and article runs.
- Worker startup triggers import catch-up when the latest import is overdue.
- Processing loop can run without calling Gmail import.
- Processing tick handles eligible documents before eligible articles.
- Processing tick does not reenter while a previous processing pass is still active.
- `POST /api/gmail/import` returns an import summary on success.
- `POST /api/gmail/import` returns an error on import failure.
- Manual import API does not wait for processing completion.
- Existing `scheduler-run-once` CLI behavior remains covered.

Frontend coverage:

- Operator workbench renders the `立即拉取邮件` button.
- Clicking the button calls `POST /api/gmail/import`.
- The button is disabled while the request is pending.
- Success displays an import summary and refreshes the relevant processing list.
- Failure displays an error and leaves existing list content intact.

## Implementation Notes

Expected files:

- [src/newspaper_translator/worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/worker.py)
- [src/newspaper_translator/document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- [src/newspaper_translator/web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [frontend/index.html](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/index.html)
- [frontend/app.js](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/app.js)
- [frontend/styles.css](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/styles.css)
- related tests under [tests](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests)

The first implementation should favor small extracted functions over a broad worker rewrite.
