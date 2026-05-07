# Dual Worker Article Drain Design

Date: 2026-05-07

Related documents:

- [Manual Gmail Import And Continuous Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-06-manual-gmail-import-and-continuous-processing-design.md)
- [Article Processing Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-02-article-processing-workbench-design.md)
- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)

## Overview

The current worker model still behaves like coarse-grained batch processing during downstream execution:

- Gmail import and document/article processing are coupled into one operational role.
- The processing path selects a bounded set of eligible work and submits that set as one batch.
- When a batch finishes, the outer worker loop sleeps before the next selection cycle.

This creates avoidable idle gaps, especially for article enrichment, because free worker capacity is not refilled immediately.

This design replaces the single mixed worker with two long-running worker roles:

- an `import` worker that performs scheduled Gmail import and document processing
- an `article` worker that sleeps while idle and drains article-processing work when tasks exist

The design keeps the current SQLite-backed task tables, claim/lock semantics, retry behavior, and single-host deployment model.

## Goals

- Split Gmail/document work and article work into two separate worker roles.
- Keep Gmail import on a timed polling schedule.
- Let the article worker remain mostly idle when no article tasks are eligible.
- Make both document and article execution refill free worker slots immediately instead of waiting for batch boundaries.
- Reuse the existing SQLite task tables and claim/lock safety model.
- Avoid introducing Redis, RabbitMQ, or another external queue.
- Preserve current retry, stale recovery, and task-status semantics as much as possible.

## Non-Goals

- Introducing true event-driven wake-up through an external queue or message bus.
- Adding more worker containers beyond the two role-specific workers needed here.
- Redesigning Gmail import, MinerU parsing, Gemini enrichment, or article identity semantics.
- Changing the product-facing article/document workbench behavior beyond the worker split.
- Replacing SQLite with another database or task system.

## Product Decisions

The approved product decisions are:

- Use two long-running worker roles instead of one mixed worker.
- Keep Gmail import and document processing together in one worker role.
- Move article post-processing into a separate worker role.
- Let the import worker poll on a timer.
- Let the article worker use an idle/active model: sleep while idle, then drain work when tasks exist.
- Do not implement true event-driven wake-up for this slice.
- Keep the system inside the current single-process-per-worker, SQLite-backed architecture.

## Recommended Architecture

### Worker Roles

#### Import Worker

The `import` worker is responsible for:

- scheduled Gmail polling
- importing newly discovered source documents
- recovering stale document-processing runs on startup
- draining eligible document-processing runs
- creating or refreshing `article_processing_runs` after document parsing succeeds

The `import` worker is not responsible for article enrichment.

#### Article Worker

The `article` worker is responsible for:

- recovering stale article-processing runs on startup
- probing for eligible article work at a low frequency while idle
- draining eligible article-processing runs when work is present

The `article` worker is not responsible for Gmail import or document parsing.

### Runtime Entry Model

Keep one Python module entrypoint and select behavior by role:

- `WORKER_ROLE=import`
- `WORKER_ROLE=article`

This keeps deployment changes small. The Docker stack can run two services from the same image while choosing different roles through environment variables.

### Data Flow

1. The `import` worker reaches its import interval and runs Gmail import.
2. Imported documents are persisted and document-processing runs exist or are created.
3. The `import` worker drains eligible document-processing runs.
4. Document processing persists final articles and creates or refreshes article-processing runs.
5. The `article` worker detects eligible article-processing runs.
6. The `article` worker drains article work until the current queue is empty, then returns to idle sleep.

## Idle And Active Behavior

### Import Worker

The import worker remains timer-driven.

Behavior:

- sleep until the next Gmail import interval check
- when overdue, run Gmail import
- after import, run document-processing drain until the currently eligible document queue is empty
- then return to waiting for the next import interval

This worker does not need a special idle/active split because its primary cadence is already governed by the Gmail polling interval.

### Article Worker

The article worker uses two states.

#### Idle State

- perform a lightweight eligibility probe at a low frequency, such as every 60 or 120 seconds
- if no eligible article-processing run exists, sleep again
- do not start a processing thread pool when the queue is empty

#### Active State

- once at least one eligible article-processing run exists, begin article drain immediately
- keep worker slots full up to `ARTICLE_WORKER_CONCURRENCY`
- whenever one article finishes, immediately attempt to claim another eligible article to refill the slot
- continue until no eligible article tasks remain and all in-flight tasks are complete
- return to idle state

This is not a true push-based wake-up model, but it behaves similarly from an operator perspective while staying compatible with SQLite and the current process model.

## Core Execution Model

The current mixed `run_processing_tick(...)` flow should be split into dedicated drain functions.

### Document Drain

Add a `run_document_processing_drain(...)` service that:

- operates only on `document_processing_runs`
- claims eligible document runs incrementally
- keeps up to `DOCUMENT_WORKER_CONCURRENCY` tasks in flight
- refills a free slot immediately after any document task completes
- exits only when no eligible document run remains and no in-flight document task is still running

### Article Drain

Add a `run_article_processing_drain(...)` service that:

- operates only on `article_processing_runs`
- claims eligible article runs incrementally
- keeps up to `ARTICLE_WORKER_CONCURRENCY` tasks in flight
- refills a free slot immediately after any article task completes
- exits only when no eligible article run remains and no in-flight article task is still running

### Why Drain Instead Of Batch

The drain model removes the main throughput bottleneck in the current implementation:

- work is no longer bounded by a preselected batch
- free concurrency is reused immediately
- the worker no longer depends on a follow-up sleep/wake cycle to continue processing queued work

### Claim Strategy

The drain functions should prefer incremental claim behavior over large prefetch lists.

Recommended pattern:

1. try to fill all free slots by selecting and claiming the next eligible tasks
2. wait for any in-flight future to complete
3. record success or failure
4. immediately try to fill freed slots again
5. stop only when the queue is empty and no in-flight task remains

This keeps the code aligned with the existing claim/lock model and reduces stale-list behavior under concurrency.

## Error Handling And Recovery

The drain redesign should not change task-state semantics.

### Document Runs

Preserve the current document run states and transitions, including:

- `pending`
- `running`
- `failed_retryable`
- `failed_terminal`
- `manual_retry_requested`
- `succeeded`

### Article Runs

Preserve the current article run states and transitions, including reuse of `last_success_input_hash` when article content has not changed.

### Failure Behavior

- a failed document task should continue using the current `fail_document_processing_run(...)` path
- a failed article task should continue using the current `fail_article_processing_run(...)` path
- one task failure must not abort the whole drain
- drain-level statistics should still accumulate total selected, completed, and failed work

### Recovery Behavior

- the `import` worker performs document stale recovery on startup
- the `article` worker performs article stale recovery on startup
- both workers continue to rely on existing `locked_by`, `lock_expires_at`, and timeout-based stale recovery rules

## Configuration Changes

### Keep

- `GMAIL_IMPORT_INTERVAL_SECONDS`
- `DOCUMENT_WORKER_CONCURRENCY`
- `ARTICLE_WORKER_CONCURRENCY`
- `STEP_RETRY_LIMIT`
- document/article lock timeout settings
- running timeout settings

### Add

- `WORKER_ROLE=import|article`
- `ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS`

### Remove Or Deprecate

- `ARTICLE_WORKER_BATCH_SIZE`
- `PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS`

`PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS` becomes unnecessary because an active drain continues working without sleeping between batches. `ARTICLE_WORKER_BATCH_SIZE` conflicts with the new refill-immediately execution model.

## Testing Strategy

Add or update tests for the following behaviors.

### Import Worker

- runs Gmail import when the import interval is overdue
- drains document-processing work until the currently eligible document queue is empty
- creates article-processing work without consuming article tasks itself

### Article Worker

- sleeps when no eligible article tasks exist
- enters active mode when article work appears
- drains article-processing work until the current queue is empty
- never exceeds `ARTICLE_WORKER_CONCURRENCY`

### Drain Semantics

- document drain refills worker slots immediately after task completion
- article drain refills worker slots immediately after task completion
- drain does not stop after a single preselected batch
- one task failure does not block remaining eligible tasks in the same drain

### Recovery

- each worker only recovers the run type it owns
- stale `running` tasks become eligible again through the existing recovery path

## Risks And Trade-Offs

- The article worker is still polling, not truly event-driven. This is intentional to avoid introducing a queue or unreliable ad hoc wake-up semantics on top of SQLite.
- Incremental claiming may increase query frequency compared with batch selection. This is acceptable because the expected queue sizes and current SQLite deployment model are small.
- Longer document drains could delay the next scheduled import check if document processing is very long-running. This is acceptable for now because the import worker remains a best-effort timed poller and the design explicitly prioritizes simpler architecture over precise multi-scheduler fairness.

## Rollout Notes

- Update `docker-compose.yml` to run separate import and article worker services from the same image.
- Keep the database schema and current processing tables unchanged for this slice.
- Implement the new role split before removing deprecated settings so the rollout can stay incremental.
