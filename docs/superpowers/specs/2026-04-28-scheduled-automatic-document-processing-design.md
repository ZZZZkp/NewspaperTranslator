# Scheduled Automatic Document Processing Design

Date: 2026-04-28

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [Newspaper Translator Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-04-22-newspaper-translator-implementation-plan.md)
- [MinerU Phase 3 Parsing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-mineru-phase-3-design.md)
- [Cross-Page Continuation Matching Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-27-cross-page-continuation-matching-design.md)
- [Article Persistence And Enrichment Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-persistence-and-enrichment-design.md)
- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)

## Overview

This document defines the first automatic end-to-end processing slice for the repository after raw Gmail import, MinerU parsing, article persistence, and single-article enrichment have already been proven independently.

The target outcome is:

- a long-running local `worker` process that triggers every 2 hours
- automatic Gmail import on each scheduler tick
- automatic document-level processing from imported PDF to persisted enriched articles
- document-level parallelism with sequential processing inside each document
- immediate step retries for transient failures
- cross-scheduler automatic retry for failed documents
- automatic stop after 2 failed document attempts
- a manual retry interface for later dashboard actions

This slice is intentionally backend-only. It prepares the data and control plane needed by the future dashboard, but it does not implement dashboard pages in this round.

## Goals

- Automatically pull target newspaper PDFs from Gmail every 2 hours
- Automatically parse each newly imported document into persisted final articles
- Automatically enrich each parsed article set and persist the latest usable outputs
- Keep repeated scheduler ticks safe through strong idempotency and duplicate avoidance
- Allow one failed document to stop without blocking other documents in the same scheduler tick
- Retry transient step failures immediately within the same document attempt
- Retry failed documents on later scheduler ticks up to 2 automatic failures total
- Stop automatic retries after the second failed document attempt
- Expose manual retry and status read surfaces for future dashboard integration
- Remain suitable for local Docker deployment on a single MacBook Pro

## Non-Goals

- Implementing dashboard pages in this slice
- Adding article-level parallel enrichment in this slice
- Building a distributed queue system
- Supporting exact wall-clock guarantees while the host laptop is asleep
- Adding alerting, notifications, or manual review workflows
- Reworking MinerU output cleanup rules in this slice

## Operating Constraint: Local Laptop Runtime

The repository is expected to run in Docker containers on one local MacBook Pro, and the laptop may sleep at any time.

This has two important consequences:

- the worker and scheduler do not run while the machine is asleep
- a "run every 2 hours" rule must be interpreted as best-effort while awake, not as a hard always-on server guarantee

The design therefore requires catch-up semantics:

- when the worker starts, it must check whether a scheduler tick is overdue and run immediately if needed
- when the worker resumes after a long pause or host sleep, the next live scheduler loop must detect the overdue interval and trigger one immediate catch-up tick
- stale `running` document workflows left behind by interruption or sleep must be recovered into retryable failure state

The system does not need to replay every missed 2-hour window separately. One catch-up tick after wake is enough because Gmail import already uses dedupe and document processing is idempotent.

## Recommended Approach

Use a single long-running `worker` process with an internal lightweight scheduler and a document-processing orchestration layer.

Why this is the right approach:

- it matches the current single-machine Docker architecture
- it keeps orchestration logic close to the existing runtime instead of introducing a new infrastructure dependency
- it provides enough control for retries, status tracking, and manual retry hooks
- it avoids over-designing the first automatic slice into a full queue platform

The automation boundary should be:

1. scheduler tick starts
2. Gmail import runs
3. eligible documents are selected
4. document workflows run in parallel
5. each document runs `parse_persist` then `enrich`
6. final state is recorded for each document and for the scheduler tick

## High-Level Architecture

The automatic pipeline should add three focused units.

### 1. Scheduler Loop

Lives inside `worker` and is responsible for:

- running every 2 hours while the worker is alive
- checking on startup whether a tick is overdue
- creating one scheduler-run record for each batch execution
- launching Gmail import before document processing
- triggering catch-up execution after host sleep or restart

### 2. Document Processing Orchestrator

Lives in a dedicated module such as `document_processing.py` and is responsible for:

- selecting eligible documents
- claiming one document for processing
- executing document steps in order
- handling immediate retries per step
- updating document processing status
- exposing one shared service path used by worker, CLI, and future web handlers

### 3. Document Processing Control Plane

Lives in new persistence helpers and tables and is responsible for:

- representing the current automation state of each document
- tracking automatic failure count and last failed step
- tracking the active scheduler run when applicable
- supporting manual retry requests without mutating parse or enrichment history rules

Existing storage layers keep their current roles:

- `import_runs` remain the Gmail import audit history
- `parse_runs` remain parse history
- `article_enrichment_runs` remain enrichment history
- the new control plane ties those units into one automatic document workflow

## Scheduler Semantics

The scheduler interval is fixed at 2 hours for the first slice.

Recommended default settings:

- `SCHEDULER_INTERVAL_SECONDS=7200`
- `DOCUMENT_WORKER_CONCURRENCY=2`
- `STEP_RETRY_LIMIT=2`
- `RUNNING_TIMEOUT_SECONDS=14400`

Behavior rules:

- when the worker starts, it runs recovery first
- after recovery, if no scheduler tick has started within the last 2 hours, the worker launches one immediate catch-up tick
- once running normally, the worker sleeps until the next interval boundary and then starts another tick
- if the worker wakes after a host sleep and notices that more than 2 hours have passed since the last scheduler tick started, it launches one immediate catch-up tick
- the scheduler may skip creating additional catch-up ticks for every missed interval; one catch-up tick is sufficient

This design favors eventual consistency over exact wall-clock replay.

## Document Selection And Parallelism

The minimal automatic work unit is one imported document.

Eligible documents must satisfy all of the following:

- the document exists in `documents`
- no active document-processing record for that document is currently `running`
- the document is not already marked `succeeded`
- the document is not already marked `failed_terminal`
- the document-processing status is one of:
  - `pending`
  - `failed_retryable`
  - `manual_retry_requested`

Processing rules:

- one scheduler tick may process multiple documents in parallel
- each document is handled by exactly one worker slot at a time
- inside one document, processing remains sequential:
  1. `parse_persist`
  2. `enrich`
- `manual_retry_requested` documents should be selected before ordinary pending documents

This preserves the user-requested document-level parallelism while keeping each document workflow simple.

## Document Workflow State Model

The document-processing control plane should use the following document statuses:

- `pending`
- `running`
- `succeeded`
- `failed_retryable`
- `failed_terminal`
- `manual_retry_requested`

Definitions:

- `pending`: ready for automatic processing
- `running`: currently claimed by an active workflow execution
- `succeeded`: the automatic pipeline completed successfully for the document
- `failed_retryable`: the latest automatic attempt failed, but the document is still eligible for future automatic retry
- `failed_terminal`: the document has reached the automatic failure ceiling and will not be retried automatically
- `manual_retry_requested`: a user has explicitly requested retry and the document should be picked up even if it had previously reached terminal automatic failure

The workflow steps should be:

- `parse_persist`
- `enrich`
- `completed`

The first slice treats parse and article persistence as one external step boundary because the repository already executes them together through one pipeline entry.

## Retry Semantics

Retry logic must exist at two levels.

### Immediate Step Retry

Each document step gets up to `STEP_RETRY_LIMIT=2` immediate retries after the initial attempt.

This retry layer is intended for transient failures such as:

- temporary MinerU transport errors
- temporary Gemini transport errors
- short-lived database locking issues
- brief network interruptions

If a step succeeds during immediate retry, the workflow continues normally and no cross-scheduler automatic failure is counted.

### Cross-Scheduler Automatic Retry

If a step still fails after all immediate retries are exhausted:

- the document workflow stops for the current scheduler tick
- the document status becomes `failed_retryable`
- `automatic_failure_count` is incremented by 1
- the failed step name and last error message are recorded

If `automatic_failure_count >= 2` after that increment:

- the document status becomes `failed_terminal`
- the scheduler must not automatically select it again

Manual retry is separate from automatic retry:

- a manual retry request moves the document to `manual_retry_requested`
- the next scheduler tick or direct retry execution may process it again
- manual retry still uses immediate step retries
- manual retry does not remove existing parse or enrichment history

## Recovery Model

The first slice should not attempt true step-level continuation after interruption.

Instead:

- on worker startup, document workflows left in `running` beyond `RUNNING_TIMEOUT_SECONDS` are treated as stale
- each stale workflow is converted to `failed_retryable` or `failed_terminal` according to the automatic failure ceiling
- the stale workflow records the timeout as its latest failure reason
- later scheduler ticks re-run the necessary document steps from their normal entrypoints

This is acceptable because the repository already keeps versioned parse and enrichment history and because repeated execution is safer than half-step resumption for the first automatic slice.

## Persistence Model

The slice should add two new tables.

### `scheduler_runs`

Represents one scheduler tick.

Suggested fields:

- `scheduler_run_id`
- `trigger_type`
- `status`
- `started_at`
- `finished_at`
- `import_run_id`
- `selected_document_count`
- `completed_document_count`
- `failed_document_count`
- `error_message`

Rules:

- `trigger_type` should support at least `interval` and `manual`
- `status` should support `running`, `succeeded`, `partial`, and `failed`
- a scheduler run may be `partial` if some documents completed and some failed

### `document_processing_runs`

Represents the current automation state for one document.

Suggested fields:

- `processing_run_id`
- `scheduler_run_id`
- `document_key`
- `status`
- `current_step`
- `automatic_failure_count`
- `last_failure_step`
- `last_error_message`
- `last_attempt_started_at`
- `last_attempt_finished_at`
- `locked_by`
- `lock_expires_at`
- `created_at`
- `updated_at`

Rules:

- each `document_key` should have exactly one current control-plane record
- this table is the current-state control plane, not the complete parse or enrichment history source
- parse and enrichment details remain in their existing run tables
- `locked_by` and `lock_expires_at` support safe claim and stale-run recovery

## Interface Boundaries

The orchestration logic should be shared rather than duplicated across entrypoints.

Recommended service boundary:

- `run_scheduler_tick(...)`
- `recover_stale_document_runs(...)`
- `process_document(...)`
- `request_manual_document_retry(...)`
- `get_document_processing_status(...)`

Recommended CLI surfaces:

- `scheduler-run-once`
- `process-pending-documents`
- `retry-document --document-key ...`
- `document-processing-status --document-key ...`

Recommended web or future dashboard surfaces:

- `GET /document-processing`
- `GET /document-processing/<document_key>`
- `POST /document-processing/<document_key>/retry`

The first slice only requires backend support for these interfaces. It does not require dashboard pages.

## Idempotency Rules

The automatic slice depends on strong repeat-safety.

Required rules:

- Gmail import dedupe remains authoritative for avoiding duplicate raw documents
- a `succeeded` document is not automatically reprocessed
- a `running` document cannot be claimed twice
- later failed parse or enrichment attempts do not erase the last usable successful outputs
- rerunning a failed document creates new parse or enrichment run history rather than mutating old runs
- one overdue scheduler catch-up tick must not create duplicate document workflows for the same document

## Logging And Observability

The worker should emit structured logs at three layers:

- scheduler tick lifecycle
- document workflow lifecycle
- step retry lifecycle

Minimum required log events:

- scheduler tick started and finished
- Gmail import started and finished
- document claimed
- document step started and finished
- immediate retry scheduled
- document marked retryable or terminal
- stale running workflow recovered
- manual retry requested

These logs should align with the repository's existing structured logging approach rather than introducing a second logging style.

## Testing Strategy

The first implementation should be test-driven and should cover four groups.

### 1. Scheduler Behavior

- worker starts and runs catch-up tick when overdue
- normal interval loop waits 2 hours between ticks
- overdue wake or restart triggers one immediate catch-up tick
- scheduler can continue processing retryable documents even when Gmail import finds no new PDFs

### 2. Document State And Selection

- `pending` documents are selected
- `manual_retry_requested` documents are selected ahead of ordinary pending documents
- `succeeded` documents are skipped
- `failed_terminal` documents are skipped automatically
- `running` documents are not selected twice

### 3. Retry And Failure Semantics

- transient `parse_persist` failure succeeds during immediate retry without increasing automatic failure count
- transient `enrich` failure succeeds during immediate retry without increasing automatic failure count
- exhausted retries mark the document `failed_retryable`
- the second automatic failure marks the document `failed_terminal`
- manual retry can reactivate a terminal document

### 4. Recovery And Idempotency

- stale `running` documents are recovered on startup
- recovered documents increment automatic failure count correctly
- repeated scheduler ticks do not duplicate workflow claims
- rerun after failure produces new parse or enrichment history while preserving prior history

## Scope Boundary For The First Implementation

This slice must include:

- worker internal scheduler
- startup and post-sleep catch-up behavior
- scheduler-run persistence
- document-processing control-plane persistence
- document-level parallel automatic processing
- immediate step retry logic
- cross-scheduler retry and terminal stop rules
- manual retry service and backend entrypoints
- read surfaces for document processing status
- logging and automated tests

This slice must not include:

- dashboard pages
- article-level parallel enrichment
- push notifications
- exact replay of every missed 2-hour interval during host sleep
- advanced human review or correction workflows

## Success Criteria

The slice is complete when all of the following are true:

- a running worker automatically imports from Gmail every 2 hours while the host is awake
- after laptop sleep or worker restart, one overdue catch-up tick runs automatically
- newly imported documents automatically flow through parse, persistence, and enrichment
- document failures do not block unrelated documents
- failed documents stop automatic retries after the second failed automatic attempt
- manual retry is available through backend interfaces
- all final outputs are persisted and ready for future dashboard reads
