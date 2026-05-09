# Worker Error Mechanism Design

Date: 2026-05-09

Related documents:

- [Dual Worker Article Drain Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-07-dual-worker-article-drain-design.md)
- [Article Stage Retry Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-30-article-stage-retry-design.md)
- [Manual Gmail Import And Continuous Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-06-manual-gmail-import-and-continuous-processing-design.md)

## Overview

The current worker runtime already isolates many task-level failures inside document and article processing state machines, but the top-level worker loops still have weak exception boundaries. If `run_startup_maintenance(...)`, `run_import_tick(...)`, `run_processing_tick(...)`, `run_article_processing_tick(...)`, or the article idle probe raises an uncaught exception, the entire worker process exits immediately.

That behavior is too brittle for normal operational noise. A single transient SQLite lock conflict or one-off query failure should not terminate the worker. At the same time, the runtime should still fail fast for clearly broken infrastructure states so container restart behavior remains useful.

This design introduces a layered worker error mechanism with explicit failure classification, bounded database retry behavior, loop-level backoff, and fatal pass-through.

## Goals

- Keep task-level business failures from terminating the worker process.
- Add bounded retry behavior for transient SQLite lock conflicts and one-off query failures.
- Preserve fail-fast behavior for configuration errors and clearly broken infrastructure states.
- Make worker failure handling explicit and testable instead of relying on broad accidental exception behavior.
- Improve operator visibility through structured loop-level logging.

## Non-Goals

- Redesigning document or article task-state semantics.
- Adding an external queue, supervisor, or process manager beyond the current container runtime.
- Converting the worker into a fully event-driven runtime.
- Introducing unbounded retry loops for database or upstream failures.
- Rewriting all repository database access patterns in one slice.

## Problem Statement

The codebase currently has two different error-handling layers:

- task execution paths usually convert business failures into persisted run state
- worker loops still allow uncaught exceptions to terminate the process

This mismatch creates two operational problems:

1. task failures are mostly survivable, but loop orchestration failures are not
2. transient SQLite contention is treated too similarly to fatal startup or schema problems

The result is a worker that is resilient at the task layer but fragile at the runtime layer.

## Product Decision

The approved behavior is:

- business-task failures must not kill the worker
- transient SQLite lock conflicts and one-off query failures should retry automatically
- loop-level failures that remain retryable after bounded retries should be logged, backed off, and retried on the next poll cycle
- fatal infrastructure failures should still terminate the process so the container can restart it

## Recommended Architecture

### Layer 1: Task-Level Failure Ownership

`process_document(...)` and `process_article_processing_run(...)` remain responsible for converting business execution failures into persisted run status such as `failed_retryable`, `failed_terminal`, or `succeeded`.

This layer should continue to own:

- parse and enrich task failures
- Gemini or MinerU business-operation failures
- step-level retries that already belong to a single document or article run

This design does not move those responsibilities upward into the worker loop.

### Layer 2: Database Retry Boundary

Introduce a small database retry wrapper for worker-orchestration database access.

This wrapper should:

- accept a callback that performs one database operation
- retry only a narrow class of transient database exceptions
- use bounded attempts with short backoff
- re-raise non-retryable failures immediately
- emit structured retry logs

Recommended default behavior:

- `max_attempts = 3`
- `sleep schedule = 0.2s, 0.5s, 1.0s`

Recommended retryable database cases:

- `sqlite3.OperationalError` containing `database is locked`
- `sqlite3.OperationalError` containing `database is busy`
- other clearly transient SQLite operational failures that are explicitly whitelisted during implementation

Recommended non-retryable database cases:

- SQL syntax errors
- missing table or column errors
- database file open failures caused by invalid path or permissions
- migration or schema mismatch problems

The implementation should prefer a whitelist model. Do not default to retrying every `OperationalError`.

### Layer 3: Loop-Level Failure Classification

Worker-loop orchestration should classify exceptions into two categories.

#### Retryable Loop Failures

These failures should be logged and converted into a controlled loop backoff instead of process termination.

Examples:

- bounded database retries exhausted for a transient lock/query path
- one-off import tick failure
- one-off processing tick failure
- one-off article drain failure
- article idle probe failure caused by a transient database read issue

#### Fatal Worker Failures

These failures should immediately terminate the worker process.

Examples:

- invalid or missing required configuration
- startup dependency construction failure caused by broken configuration
- database schema mismatch
- database path unavailable or unusable
- explicit fatal infrastructure exceptions raised by lower layers

The worker should use explicit fatal classification rather than broad best-effort swallowing.

### Layer 4: Worker Loop Backoff

When a retryable loop failure escapes a single tick after bounded local retries, the worker should:

- emit a structured `worker.loop.retryable_failure` log
- increase a consecutive loop-failure counter
- sleep using bounded backoff
- continue the outer loop instead of exiting

Recommended backoff schedule:

- first consecutive retryable loop failure: `5s`
- second consecutive retryable loop failure: `15s`
- third and later consecutive retryable loop failures: `60s`

Any successful loop iteration should reset the consecutive failure counter to zero and emit a `worker.loop.recovered` log when recovering from a previous error streak.

## Detailed Design

### New Runtime Helpers

Add small runtime helpers in `worker.py` or a tightly related worker-only module:

- a helper to decide whether a database exception is retryable
- a helper to execute a callback with bounded database retries
- a helper to classify whether an exception is fatal at the worker-loop level
- a helper to compute loop backoff from consecutive failure count

These helpers should remain worker-oriented rather than becoming a generic repo-wide abstraction in this slice.

### New Exception Shape

The runtime should introduce explicit exception classes for worker orchestration where that improves clarity.

Recommended shapes:

- `RetryableWorkerLoopError`
- `FatalWorkerError`

These do not need to replace existing task exceptions. Their purpose is to make top-level orchestration intent explicit.

### Startup Behavior

Startup should remain strict.

`build_*_from_env(...)`, dependency creation, and startup maintenance should continue to fail fast when they encounter non-transient infrastructure problems.

Transient database access during startup maintenance may use the same bounded database retry wrapper. If retryable startup database operations still fail after retries, the error may be reclassified as retryable or fatal based on the exact failure source during implementation, but configuration and schema errors must remain fatal.

### Import Worker Runtime

The import worker loop should wrap these boundaries:

- startup maintenance
- overdue import tick
- processing tick

Expected behavior:

1. if a fatal error occurs, terminate the process
2. if a retryable loop error occurs, log it, back off, and continue
3. if the iteration succeeds, reset loop-failure state and use the normal active or idle poll interval

The worker should not silently swallow exceptions and continue without logging.

### Article Worker Runtime

The article worker loop should wrap these boundaries:

- stale article recovery on startup
- article work existence probe
- article processing drain

Expected behavior mirrors the import worker:

1. fatal infrastructure problems terminate the process
2. retryable loop failures log, back off, and continue probing later
3. successful iterations reset the failure streak

### Database Retry Scope

This design intentionally scopes database retries to orchestration-critical access points rather than every SQLite interaction in the repository.

The first slice should cover the worker-critical paths most likely to fail due to transient contention:

- eligible-run listing used by idle probes and drains
- claim operations used by drains
- scheduler run creation and finalization used during ticks
- latest-run lookup used by import overdue checks

The implementation may extend coverage to adjacent worker-owned database helpers when the ownership boundary is clear, but should avoid a large unrelated persistence refactor.

## Logging

Add structured worker logs for:

- `worker.db.retry_scheduled`
- `worker.db.retry_exhausted`
- `worker.loop.retryable_failure`
- `worker.loop.fatal_failure`
- `worker.loop.recovered`

Recommended fields:

- `worker_role`
- `stage`
- `attempt`
- `max_attempts`
- `sleep_seconds`
- `error_type`
- `error_message`

This gives operators enough context to distinguish:

- task failures inside the state machine
- transient loop failures the worker survived
- fatal runtime failures that intentionally caused exit

## Testing Strategy

Add focused tests that prove the runtime behavior instead of relying only on indirect failure expectations.

Required coverage:

- retryable SQLite lock/query errors are retried and can eventually succeed
- bounded database retry exhaustion does not terminate the worker when the error is classified retryable
- fatal startup or fatal loop errors terminate the worker
- retryable loop failures trigger loop backoff
- a successful iteration resets the consecutive loop-failure counter
- article and import worker roles both use the same fatal versus retryable behavior model

Tests should remain deterministic by stubbing sleep functions and injected callbacks.

## Trade-Offs

### Why Not Swallow Everything

Defaulting to `except Exception: continue` would stop the immediate crashes, but it would also hide real infrastructure failures and make restart-based recovery less meaningful. That approach optimizes for short-term uptime at the cost of diagnosability and operational correctness.

### Why Not Build A Full Supervisor

An in-process supervisor abstraction would also solve the problem, but it adds more moving parts than needed for this slice. The current worker runtime only needs explicit boundaries, classification, and bounded backoff.

### Why Use A Whitelist For Database Retries

Retrying all `sqlite3.OperationalError` instances is too broad. Some operational errors are transient contention, while others reflect permanent schema or filesystem problems. A whitelist keeps fail-fast behavior intact.

## Rollout Notes

- Keep defaults conservative so the worker remains understandable under local Docker Compose.
- Prefer introducing the retry and classification helpers first, then wiring them into worker loops and the most relevant database access points.
- Preserve current task status behavior so operator-facing retry controls continue to work as before.

## Acceptance Criteria

- a single transient SQLite lock conflict no longer causes worker process exit
- a one-off query failure on a worker loop path retries automatically with bounded backoff
- exhausted retryable loop failures do not kill the worker and instead trigger loop backoff
- fatal configuration or schema failures still terminate the worker process
- structured logs make retryable versus fatal worker failures distinguishable
- both import and article worker roles follow the same runtime error policy
