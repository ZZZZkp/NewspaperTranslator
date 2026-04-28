# Scheduled Automatic Document Processing Plan

Date: 2026-04-28

Related documents:

- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)
- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [Article Persistence And Enrichment Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-persistence-and-enrichment-design.md)
- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)

## Goal

This plan turns the approved automatic-processing design into a staged delivery order that reaches a reliable unattended backend pipeline:

- a long-running worker with an internal 2-hour scheduler
- automatic Gmail import
- automatic document-level parse and enrich execution
- strong dedupe and repeat-safe processing
- immediate retry for transient step failures
- cross-scheduler retry for failed documents
- terminal stop after 2 automatic failures
- manual retry entrypoints for later dashboard use

## Execution Status

Status on 2026-04-28: in progress.

Completed so far in the repository:

- added migration `0006_scheduled_automatic_document_processing`
- added durable `scheduler_runs` persistence
- added durable `document_processing_runs` persistence
- added repository helpers to:
  - create and finalize scheduler runs
  - create or upsert document-processing state
  - claim one document safely without double claim
  - list eligible documents in priority order with `manual_retry_requested` first
- added targeted TDD coverage for the new migration and persistence helpers

Not implemented yet:

- document failure-state mutation helpers
- manual retry mutation helpers
- stale-running recovery helpers
- document-level parse and enrich orchestration
- worker scheduler loop and CLI entrypoints

The repository already has the main building blocks needed for this slice:

- Gmail import with audit history and checkpointing
- durable raw PDF storage in `documents`
- MinerU-backed parse and article persistence through `phase3-persist-document`
- single-article enrichment through `phase3-enrich-article`
- latest-visible parse and enrichment version rules

The main gaps are orchestration, scheduling, document-level control-plane state, recovery, and operator-facing retry/status entrypoints.

## Current Starting Point

The current repository behavior is close to the automatic target, but still disconnected:

- Gmail import creates raw documents and a very lightweight `processing_tasks` record
- parse and enrich flows exist, but they only run through manual CLI entrypoints
- the current `worker` is only a startup-check process and does not orchestrate document work
- the current `web` surface exposes import-audit reads, not document-processing control or status
- there is no scheduler state, no document automatic-failure ceiling, and no stale-run recovery

This plan fills those gaps without expanding scope into dashboard pages.

## Recommended Delivery Order

### Slice 1: Scheduler And Document-Processing Persistence

Add the control-plane schema and storage helpers needed by the automatic worker.

Scope:

- add migration for `scheduler_runs`
- add migration for `document_processing_runs`
- add repository helpers to:
  - create and finalize scheduler runs
  - create or upsert document-processing state
  - claim one document safely
  - mark document success, retryable failure, or terminal failure
  - request manual retry
  - recover stale running documents
  - list eligible documents in priority order

Why first:

- every later slice depends on authoritative current-state persistence
- this keeps scheduler and orchestration logic out of raw SQL

Exit criteria:

- one scheduler run can be created and finalized
- one imported document can hold current automation state in `document_processing_runs`
- claim and update helpers support safe single-document ownership

Current status on 2026-04-28:

- scheduler-run create/finalize: done
- document current-state persistence: done
- idempotent document state initialization: done
- safe single-document claim: done
- eligible-document priority ordering: done
- failure-state and recovery helpers: not started

### Slice 2: Document Processing Orchestration Service

Introduce a focused service module such as `document_processing.py`.

Scope:

- define orchestration entrypoints such as:
  - `process_document(...)`
  - `request_manual_document_retry(...)`
  - `recover_stale_document_runs(...)`
- run document steps in order:
  1. `parse_persist`
  2. `enrich`
- wrap each step with immediate retry behavior
- record `current_step`, failure details, and automatic failure count
- stop automatic retries after the second failed automatic attempt

Why second:

- the worker, CLI, and future web handlers should all call the same service layer
- retry and state semantics are easier to test before introducing timer logic

Exit criteria:

- a single document can be processed end to end through one shared orchestration path
- transient failures can succeed during immediate retry without increasing automatic failure count
- exhausted retries produce `failed_retryable` and later `failed_terminal` correctly

### Slice 3: Document-Level Batch Enrichment Execution

Expand enrichment from one manually chosen article to one parsed document's latest visible article set.

Scope:

- add repository helper to list latest visible final articles for one document
- add orchestration helper such as `enrich_document_articles(...)`
- process each document's latest visible articles sequentially in the first slice
- propagate partial or failed article enrichment into document-level failure semantics
- keep existing article-level enrichment history rules unchanged

Why third:

- the automatic document pipeline needs a document-facing enrich boundary, not a manual article id boundary
- this is the smallest change that makes parse and enrich compose automatically

Exit criteria:

- one parsed document can automatically enrich its current visible article set
- article-level failures remain visible in existing enrichment history
- document orchestration can determine whether the document overall succeeded or failed

### Slice 4: Worker Scheduler Loop And Catch-Up Behavior

Turn the existing `worker` from a startup-check loop into a real internal scheduler.

Scope:

- run recovery on startup
- check whether a scheduler tick is overdue
- trigger one catch-up tick immediately when overdue
- run repeated ticks every `SCHEDULER_INTERVAL_SECONDS`
- call Gmail import first in each tick
- select eligible documents and submit them to document worker slots
- persist scheduler-run counts and final status

Why fourth:

- persistence and orchestration should already be proven before timer-driven background execution begins
- this isolates scheduler bugs from core business-state bugs

Exit criteria:

- the worker can perform one full scheduler tick end to end
- overdue startup and post-sleep catch-up behavior are both test-covered
- a tick that finds no new Gmail documents can still process retryable documents

### Slice 5: Document-Level Parallelism And Safe Claiming

Add the concurrency layer for processing multiple documents in the same scheduler tick.

Scope:

- introduce fixed-size document worker concurrency
- ensure only one worker slot can claim one `document_key`
- prioritize `manual_retry_requested` ahead of `pending`
- prevent duplicate claim during overlapping checks
- keep single-document step order sequential

Why fifth:

- concurrency is valuable, but it should build on top of already-correct document-state transitions
- this preserves the requested document-level parallelism without mixing it into the initial control-plane work

Exit criteria:

- one scheduler tick can process multiple documents concurrently
- the same document cannot be claimed twice
- later document failures do not block other documents in the same tick

### Slice 6: CLI And Minimal Read/Write Surfaces

Expose narrow operator-facing entrypoints after the worker path is stable.

Scope:

- add CLI commands:
  - `scheduler-run-once`
  - `process-pending-documents`
  - `retry-document --document-key ...`
  - `document-processing-status --document-key ...`
- add minimal read and retry-ready service hooks that future web endpoints can call
- if low-cost, add backend-only web handlers for:
  - `GET /document-processing`
  - `GET /document-processing/<document_key>`
  - `POST /document-processing/<document_key>/retry`

Why sixth:

- this provides practical observability and manual control without waiting for dashboard pages
- it avoids building interface surfaces before the workflow semantics settle

Exit criteria:

- an operator can trigger one scheduler tick manually
- an operator can inspect document-processing state
- an operator can request manual retry for a terminal or retryable document

### Slice 7: Recovery Validation And Local Runtime Hardening

Validate the unattended local-laptop behavior explicitly.

Scope:

- test stale running document recovery
- test restart behavior after interrupted runs
- test catch-up scheduling after elapsed interval
- validate structured logging around scheduler and document lifecycle
- confirm automatic processing remains safe under repeated local runs

Why seventh:

- this slice is where the design's "MacBook may sleep" assumption becomes real
- unattended behavior matters more than throughput polish for this milestone

Exit criteria:

- stale `running` documents are recovered deterministically
- the worker can restart and continue processing safely
- catch-up behavior is reliable enough for local laptop deployment

## Suggested File-Level Delivery

### Likely production files

- [worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/worker.py)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
- [article_enrichment.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_enrichment.py)
- new module such as [document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- new migration such as [0006_scheduled_automatic_document_processing.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0006_scheduled_automatic_document_processing.sql)

### Likely test files

- [test_worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_worker.py)
- [test_manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_manage.py)
- new tests such as [test_document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_document_processing.py)
- [test_article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_article_store.py)
- possibly [test_web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_web.py) if minimal endpoints are added in this slice

## TDD Queue

Each slice should follow the same loop:

1. write one failing test
2. run the narrowest possible target and verify RED
3. add the minimum implementation to reach GREEN
4. rerun the targeted test
5. refactor while staying green

Recommended first tests in order:

1. `applies scheduled automatic processing schema migration`
2. `creates and finalizes a scheduler run`
3. `claims one eligible document processing run without double claim`
4. `marks document failed_retryable after exhausted parse retries`
5. `marks document failed_terminal after second automatic failure`
6. `manual retry reactivates a terminal document`
7. `processes one document through parse persist and document enrichment`
8. `document enrichment loads latest visible articles for one document`
9. `worker startup runs catch_up_tick_when_overdue`
10. `worker recovery converts stale running documents to retryable failure`
11. `scheduler tick can continue retryable documents when gmail import finds nothing new`
12. `scheduler tick processes multiple documents without duplicate claims`
13. `retry_document command requests manual retry`
14. `document_processing_status command returns current state`

## Success Criteria

We should consider this automatic-processing milestone complete when the repository can:

- run one long-lived worker locally
- wake up every 2 hours while the machine is awake
- run one catch-up tick after restart or host sleep when overdue
- import Gmail PDFs automatically
- process multiple documents in parallel without double-running the same document
- parse and enrich documents end to end without manual per-document commands
- stop automatic retries after the second failed automatic attempt
- expose manual retry and status inspection through backend interfaces

## What We Are Not Doing Yet

- dashboard pages
- article-level parallel enrichment
- advanced scheduling policies beyond fixed 2-hour interval
- push notifications or alerting
- exact replay of every missed 2-hour scheduler window during laptop sleep
- deeper prompt or parsing-quality work outside the already approved scope

## Risks To Watch

- letting the new document-processing control plane drift out of sync with existing parse or enrichment history
- overloading `worker.py` instead of moving orchestration into a dedicated module
- making catch-up scheduling depend on perfect wall-clock behavior despite local laptop sleep
- coupling manual retry semantics too tightly to future dashboard requirements before the backend stabilizes
