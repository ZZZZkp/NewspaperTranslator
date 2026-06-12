# Worker Resilience: Container Restart and Transient-Error Retry Design

Date: 2026-06-12

Related documents:

- [Worker Error Mechanism Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-09-worker-error-mechanism-design.md)
- [Dual Worker Article Drain Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-07-dual-worker-article-drain-design.md)
- [Manual Gmail Import And Continuous Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-06-manual-gmail-import-and-continuous-processing-design.md)

## Overview

On 2026-06-11 the import `worker` container exited with code 1 during a scheduled
Gmail import tick and stayed dead for roughly 19 hours, so no email was pulled
that day. The `article-worker` kept running because it does not perform Gmail
imports.

Root cause is two compounding gaps:

1. **Application layer.** A transient `requests.exceptions.ReadTimeout` from
   `gmail.googleapis.com` was classified as a fatal worker error and terminated
   the loop. The [Worker Error Mechanism Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-09-worker-error-mechanism-design.md)
   explicitly listed "one-off import tick failure" as a *retryable* loop failure,
   but the implementation only whitelisted SQLite lock errors as retryable and
   let everything else fall through to the fatal default branch. Transient
   network errors were never added to the retryable whitelist.
2. **Container layer.** No service in `docker-compose.yml` declares a `restart`
   policy, so once the process exited Docker never restarted it.

This design closes both gaps: it extends the retryable whitelist to cover
transient network errors (root cause), and adds a bounded container restart
policy as a safety net for any other unexpected exit.

## Goals

- Stop transient Gmail/network errors from terminating the import worker.
- Reuse the existing loop backoff-and-continue machinery rather than adding new
  control flow.
- Add an automatic container restart safety net with a bounded retry count so an
  unexpected exit does not require manual intervention, while a persistently
  broken service still stops and becomes visible.
- Preserve fail-fast behavior for configuration and programming errors.

## Non-Goals

- Redesigning the fatal-vs-retryable framework from the 2026-05-09 design; this
  slice only extends the retryable whitelist.
- Tightening `depends_on` startup ordering (kept as-is per decision below).
- Removing the unused postgres `db` service.
- Adding external supervisors, alerting, or monitoring beyond the container
  restart policy.
- Auto-start after host/Docker daemon reboot (explicitly traded away; see
  Decisions).

## Background: current runtime facts

- Two worker containers run the same module, distinguished by `WORKER_ROLE`:
  `worker` (role `import`, runs Gmail import on a ~2h cadence) and
  `article-worker` (role `article`).
- `DATABASE_URL` resolves to `sqlite:////data/newspaper-translator.db`. All
  services use SQLite on the `app-data` volume. The postgres `db` container is
  **not used at runtime**; each service's `depends_on: db` is therefore a
  misleading no-op for data access.
- The only real runtime dependency is `frontend -> web` (nginx reverse-proxies
  API calls to web). nginx tolerates web being temporarily down (returns 502
  without crashing), so this edge does not create a restart crash-loop risk.
- The loop already implements retryable handling: a `RetryableWorkerLoopError`
  logs `worker.loop.retryable`, increments a consecutive-failure counter, sleeps
  with backoff (5s / 15s / 60s), and continues; a successful iteration logs
  `worker.loop.recovered`. **No loop changes are needed** to absorb transient
  errors once they are classified retryable.

## Decisions

These were confirmed with the operator during design:

- **Restart policy: `restart: on-failure:5`** on long-running services. This is
  the only Docker Compose short-syntax option that caps restart attempts.
  `unless-stopped`/`always` cannot express a count, and the long-form
  `deploy.restart_policy.max_attempts` is honored only by Docker Swarm, not by
  `docker compose up`.
  - Accepted trade-off: `on-failure` does **not** auto-start containers after a
    host or Docker daemon reboot. After a reboot the operator runs
    `docker compose up -d`.
- **Startup ordering unchanged.** Keep `depends_on` at `condition:
  service_started`. The only real dependency (`frontend -> web`) is
  fault-tolerant, so tightening to `service_healthy` is unnecessary here.
- **Keep the postgres `db` service** even though it is currently unused.

## Architecture

### Layer A: Container restart policy

Add `restart: on-failure:5` to every service in `docker-compose.yml`:
`frontend`, `web`, `worker`, `article-worker`, and `db`.

Semantics:

- Docker restarts a container only when it exits with a non-zero code, up to 5
  consecutive times. After 5 consecutive failures Docker gives up and the
  container stays `Exited`, where it is visible via `docker compose ps` and the
  service healthcheck.
- Docker resets the failure counter once a container runs successfully for a
  sustained period, so isolated later failures get a fresh budget.
- `db` receives the policy for consistency and future-proofing (in case the
  stack later switches `DATABASE_URL` to postgres), even though it is unused
  today.

Rationale for `N = 5`: Layer B removes the common transient-network crash, so
remaining crashes are structural (bad config, code bug). Five consecutive
crashes indicate a problem that will not self-heal, so the worker should stop and
become observable rather than spin forever. `N` is a single, easily adjustable
value.

### Layer B: Transient-error classification

Extend `_is_retryable_worker_loop_error(exc)` in
`src/newspaper_translator/worker.py` to treat transient network failures as
retryable, in addition to the existing SQLite lock cases:

- `requests.exceptions.Timeout` (covers `ReadTimeout` and `ConnectTimeout`)
- `requests.exceptions.ConnectionError`

This keeps the whitelist philosophy from the 2026-05-09 design: only clearly
transient errors are retryable. Programming/configuration errors (`ValueError`
and the catch-all default) remain fatal.

Classification ordering is already safe: `_raise_for_worker_loop_error` checks
fatal first (`_is_fatal_worker_error`, which matches only `FatalWorkerError` and
`ValueError`), then retryable. Network exceptions are not `ValueError`, so they
reach the retryable branch.

No changes to `run_worker_loop` control flow: once classified retryable, the
existing backoff-and-continue path handles logging, backoff, and continuation.

### How the layers combine (defense in depth)

- Layer B eliminates the common case (network blip) so the worker never dies
  from it; it logs a warning and retries on the next cycle.
- Layer A catches everything else (OOM, unexpected exceptions, structural
  errors) by restarting up to 5 times, then stops so the failure is visible.

## Open item to verify during implementation

The import tick only runs when `should_run_catch_up_tick(...)` opens (~2h
window). Verify whether a failed import advances the "last run" timestamp that
gates the next attempt. If it does, a failed import would wait ~2h for the next
window rather than retrying on the 60s loop backoff. The worker survives either
way (Layer B goal met), but the implementation should confirm prompt retry and,
if needed, ensure a failed import does not push the gating timestamp forward.
This is a verification/refinement item, not a change to the core design.

## Testing strategy

Unit tests (deterministic; stub sleep where the loop is exercised):

- `_is_retryable_worker_loop_error(requests.exceptions.ReadTimeout(...))` is
  `True`.
- `_is_retryable_worker_loop_error(requests.exceptions.ConnectionError(...))` is
  `True`.
- `_is_retryable_worker_loop_error(requests.exceptions.ConnectTimeout(...))` is
  `True`.
- Existing SQLite lock classification still returns `True` (regression guard).
- A `ValueError` still classifies as fatal (regression guard).
- `_raise_for_worker_loop_error(ReadTimeout, stage="import_tick")` raises
  `RetryableWorkerLoopError`, not `FatalWorkerError`.

Loop-level test (reuse the existing `max_loops` harness):

- Inject an import tick that raises `ReadTimeout` once; assert the loop logs
  `worker.loop.retryable` and continues instead of exiting, and that a
  subsequent successful tick logs `worker.loop.recovered`.

Layer A is not unit-testable; verify by inspecting `docker-compose.yml` and, on
a running stack, `docker inspect` of the restart policy.

## Acceptance criteria

- A transient `requests` timeout or connection error on the import tick no longer
  terminates the worker; it is logged as retryable and retried with backoff.
- Existing SQLite-lock retry behavior and fatal `ValueError` behavior are
  unchanged.
- Every Compose service declares `restart: on-failure:5`.
- A worker that exits non-zero is restarted by Docker up to 5 consecutive times,
  then stays `Exited` and visible.
- Both worker roles continue to follow the same fatal-vs-retryable policy.
