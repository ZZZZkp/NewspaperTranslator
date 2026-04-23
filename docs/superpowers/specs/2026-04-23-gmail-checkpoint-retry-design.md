# Gmail Checkpoint And Retry Design

Date: 2026-04-23

## Overview

This slice adds two operational behaviors to the Gmail import flow:

- incremental checkpointing based on a time window
- durable retry tracking for failed Gmail messages

The checkpoint should reduce repeated scans for normal imports.
The retry flow should make failed target messages recoverable even after the checkpoint moves forward.

## Scope

This version should:

- keep Gmail incremental state as a time-based checkpoint
- advance the checkpoint only after a run finishes with `succeeded` or `partial`
- base checkpoint advancement on the newest target message that actually entered processing
- retry failed Gmail messages at message level, while keeping attachment/link audit at item level
- run one automatic retry sweep after each `gmail-import`
- expose one manual retry command through `manage`

This version should not add Gmail pagination token checkpoints.

## Data Model

### `import_checkpoints`

One row per checkpoint key.

Suggested fields:

- `source_name`
- `checkpoint_type`
- `checkpoint_value`
- `updated_at`

For Gmail this slice uses:

- `source_name = gmail`
- `checkpoint_type = message_internal_date`

### `failed_messages`

One row per Gmail message that still needs retry tracking.

Suggested fields:

- `message_id`
- `source_name`
- `message_internal_date`
- `retry_state`
- `retry_attempt_count`
- `last_run_id`
- `created_at`
- `updated_at`

Retry states:

- `pending`
- `resolved`
- `failed_final`

### Audit Extensions

`import_runs` should store:

- `checkpoint_before`
- `checkpoint_after`

`import_run_items` should store:

- `message_internal_date`

## Runtime Semantics

### Normal Import

1. Read the Gmail time checkpoint before starting the fetch.
2. Narrow the Gmail query with a time constraint when a checkpoint exists.
3. Process target messages with the existing Gmail import flow.
4. Record each target message's `internalDate`.
5. If the run ends as `succeeded` or `partial`, advance the checkpoint to the newest processed target message time.

### Failure Tracking

- If a target message has any failed item, mark that Gmail message as `pending`.
- If all failed items for that message later succeed, mark the message as `resolved`.
- Each failed message gets at most one retry attempt.
- If the retry attempt still leaves failed items, mark the message as `failed_final`.

### Retry Execution

Two entrypoints should use the same retry logic:

- automatic retry after each `gmail-import`
- manual retry via `manage gmail-retry-failures`

Retry execution should refetch and reprocess the whole Gmail message, not only the failed item.
Idempotency should still rely on the existing duplicate-safe document import path.

## Query And Reporting

This slice only needs minimal exposure:

- include checkpoint fields in import run records
- allow the manual retry command to report retried and resolved message counts

The existing run and item query surfaces should continue to work.

## Testing Strategy

Implement with TDD in small steps:

1. schema coverage for checkpoints, failed message tracking, and audit-field extensions
2. checkpoint repository coverage for read/update behavior
3. failed-message repository coverage for pending/resolved/final transitions
4. Gmail integration coverage for narrowed query behavior and checkpoint advancement
5. Gmail integration coverage for automatic retry after normal import
6. management command coverage for manual retry execution
