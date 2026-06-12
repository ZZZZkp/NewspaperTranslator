# Worker Resilience: Restart and Transient-Error Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop transient Gmail/network errors from killing the import worker, and add a bounded container restart policy so any other unexpected exit auto-recovers up to a limit.

**Architecture:** Two independent layers. Layer B (application) extends the existing retryable-error whitelist in `worker.py` to cover `requests` timeouts/connection errors, so the existing backoff-and-continue loop absorbs them instead of treating them as fatal. Layer A (container) adds `restart: on-failure:5` to every `docker-compose.yml` service.

**Tech Stack:** Python 3.11, `unittest`, `requests` 2.31, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-06-12-worker-resilience-restart-design.md`

---

## File Structure

- `src/newspaper_translator/worker.py` — add `import requests`; extend `_is_retryable_worker_loop_error(...)` to classify transient network errors as retryable. No control-flow changes.
- `tests/test_worker.py` — add unit tests for the new classification cases and one loop-level test proving a network-timeout import tick does not terminate the worker.
- `docker-compose.yml` — add `restart: on-failure:5` to `frontend`, `web`, `worker`, `article-worker`, `db`.

---

## Task 1: Classify transient network errors as retryable

**Files:**
- Modify: `src/newspaper_translator/worker.py` (imports near top; `_is_retryable_worker_loop_error` at lines ~599-615)
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write the failing tests**

Add these three test methods to the existing test class in `tests/test_worker.py` that already contains `test_database_locked_operational_error_is_retryable` (around line 597):

```python
    def test_read_timeout_is_retryable(self) -> None:
        import requests
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertTrue(
            _is_retryable_worker_loop_error(
                requests.exceptions.ReadTimeout("read timed out")
            )
        )

    def test_connect_timeout_is_retryable(self) -> None:
        import requests
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertTrue(
            _is_retryable_worker_loop_error(
                requests.exceptions.ConnectTimeout("connect timed out")
            )
        )

    def test_connection_error_is_retryable(self) -> None:
        import requests
        from newspaper_translator.worker import _is_retryable_worker_loop_error

        self.assertTrue(
            _is_retryable_worker_loop_error(
                requests.exceptions.ConnectionError("connection refused")
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_worker.py -k "timeout or connection_error" -v`
Expected: 3 tests FAIL — `_is_retryable_worker_loop_error` returns `False` for these (currently they fall through to the final `return False`).

- [ ] **Step 3: Add the `requests` import**

In `src/newspaper_translator/worker.py`, the top imports currently are:

```python
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import time
```

Change to add `import requests` as a third-party import:

```python
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import time

import requests
```

- [ ] **Step 4: Extend the classification function**

In `src/newspaper_translator/worker.py`, the current function is:

```python
def _is_retryable_worker_loop_error(exc: BaseException) -> bool:
    if isinstance(exc, RetryableWorkerLoopError):
        return True
    if isinstance(exc, FatalWorkerError):
        return False
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return any(
            lock_message in message
            for lock_message in (
                "database is locked",
                "database table is locked",
                "database schema is locked",
            )
        )
    return False
```

Replace it with (adds the transient-network branch after the `FatalWorkerError` guard, before the sqlite branch):

```python
def _is_retryable_worker_loop_error(exc: BaseException) -> bool:
    if isinstance(exc, RetryableWorkerLoopError):
        return True
    if isinstance(exc, FatalWorkerError):
        return False
    if isinstance(
        exc,
        (requests.exceptions.Timeout, requests.exceptions.ConnectionError),
    ):
        return True
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return any(
            lock_message in message
            for lock_message in (
                "database is locked",
                "database table is locked",
                "database schema is locked",
            )
        )
    return False
```

Note: `requests.exceptions.Timeout` is the base class of both `ReadTimeout` and `ConnectTimeout`, so a single `isinstance` check covers both.

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_worker.py -k "timeout or connection_error" -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Run regression guards to confirm existing classification is unchanged**

Run: `.venv/bin/python -m pytest tests/test_worker.py -k "retryable or fatal or operational_error or value_error" -v`
Expected: All PASS, including `test_database_locked_operational_error_is_retryable`, `test_non_locked_operational_error_is_not_retryable`, and `test_value_error_is_treated_as_fatal`.

- [ ] **Step 7: Commit**

```bash
git add src/newspaper_translator/worker.py tests/test_worker.py
git commit -m "$(cat <<'EOF'
fix: classify transient network errors as retryable in worker loop

A requests ReadTimeout from the Gmail API was hitting the fatal default
branch and terminating the import worker. Add requests Timeout and
ConnectionError to the retryable whitelist so the existing loop backoff
absorbs them instead of crashing.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Loop-level test — a network-timeout import tick does not kill the worker

**Files:**
- Test: `tests/test_worker.py`

This proves the end-to-end behavior: the regression that caused the 2026-06-11 outage. Before Task 1's fix, an import tick raising `ReadTimeout` made `run_worker_loop` raise `FatalWorkerError`; after the fix it must back off and continue.

- [ ] **Step 1: Write the test**

Add this test method to the same class in `tests/test_worker.py`, mirroring the existing `test_worker_loop_runs_import_when_import_interval_is_overdue` harness (around line 367):

```python
    def test_import_tick_network_timeout_is_retryable_not_fatal(self) -> None:
        import requests

        self.assertIsNotNone(run_worker_loop)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "GMAIL_IMPORT_INTERVAL_SECONDS": "7200",
            "PROCESSING_POLL_INTERVAL_SECONDS": "60",
        }
        sleeps: list[int] = []

        def failing_import(*, trigger_type: str) -> str:
            raise requests.exceptions.ReadTimeout("read timed out")

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-06T12:31:00",
            sleep_fn=lambda seconds: sleeps.append(seconds),
            max_loops=1,
            run_startup_maintenance_fn=lambda **kwargs: None,
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-06T10:30:00",
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=failing_import,
            run_processing_tick_fn=lambda: SimpleNamespace(did_work=False),
        )

        # Retryable path: the loop slept the first backoff (5s) and returned
        # normally instead of raising FatalWorkerError.
        self.assertIn(5, sleeps)
```

`SimpleNamespace` is already imported at the top of `tests/test_worker.py` (`from types import SimpleNamespace`).

- [ ] **Step 2: Run the test to verify behavior**

Run: `.venv/bin/python -m pytest tests/test_worker.py -k "network_timeout_is_retryable_not_fatal" -v`
Expected: PASS (with Task 1 applied). If Task 1 were reverted, this test would FAIL because `run_worker_loop` would raise `FatalWorkerError`.

- [ ] **Step 3: Run the full worker test file**

Run: `.venv/bin/python -m pytest tests/test_worker.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_worker.py
git commit -m "$(cat <<'EOF'
test: import-tick network timeout backs off instead of crashing worker

Regression test for the 2026-06-11 outage where a Gmail ReadTimeout
terminated the import worker loop.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `restart: on-failure:5` to all Compose services

**Files:**
- Modify: `docker-compose.yml`

Each service name (`  frontend:`, `  web:`, `  worker:`, `  article-worker:`, `  db:`) is unique, so insert `restart: on-failure:5` as the first key under each. Services use 2-space indentation for the name and 4-space for keys.

- [ ] **Step 1: Add restart policy to `frontend`**

Old:
```yaml
  frontend:
    build:
```
New:
```yaml
  frontend:
    restart: on-failure:5
    build:
```

- [ ] **Step 2: Add restart policy to `web`**

Old:
```yaml
  web:
    build:
```
New:
```yaml
  web:
    restart: on-failure:5
    build:
```

- [ ] **Step 3: Add restart policy to `worker`**

Old:
```yaml
  worker:
    build:
```
New:
```yaml
  worker:
    restart: on-failure:5
    build:
```

- [ ] **Step 4: Add restart policy to `article-worker`**

Old:
```yaml
  article-worker:
    build:
```
New:
```yaml
  article-worker:
    restart: on-failure:5
    build:
```

- [ ] **Step 5: Add restart policy to `db`**

Old:
```yaml
  db:
    image: postgres:16-alpine
```
New:
```yaml
  db:
    restart: on-failure:5
    image: postgres:16-alpine
```

- [ ] **Step 6: Validate the compose file and count the policies**

Run: `docker compose config >/dev/null && echo "compose valid" && grep -c "restart: on-failure:5" docker-compose.yml`
Expected: `compose valid` followed by `5`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
ops: add restart on-failure:5 to all compose services

Safety net so an unexpected non-zero exit auto-restarts up to 5 times,
then stays Exited and visible. Caps restarts (unless-stopped/always
cannot; deploy.restart_policy is swarm-only) at the cost of no
auto-start after host/daemon reboot.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Apply the restart policy to the running stack

**Files:** none (operational).

The restart policy is recorded on a container at creation time, so it only takes effect after the containers are recreated. The Docker Desktop start button does NOT apply it — `docker compose up -d` is required (it recreates services whose config changed).

> **Note:** This recreates the running `worker`, `web`, `frontend`, and `db` containers (brief downtime). The import worker was already restarted earlier in this session; recreation re-applies the policy. Confirm timing is acceptable before running.

- [ ] **Step 1: Recreate containers so the new policy is applied**

Run: `docker compose up -d`
Expected: Compose reports the affected services as `Recreated` / `Started`.

- [ ] **Step 2: Verify the restart policy is on the live containers**

Run: `for c in worker web frontend article-worker db; do printf "%s: " "$c"; docker inspect "newspapertranslator-$c-1" --format '{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}'; done`
Expected: each line prints `on-failure:5`.

- [ ] **Step 3: Confirm the worker is healthy and importing**

Run: `docker compose ps worker && docker logs newspapertranslator-worker-1 --since 2m 2>&1 | grep -iE "startup|error|fatal" | tail -5`
Expected: worker `Up ... (healthy)` (after the healthcheck settles), a `worker.startup` log line, and no fatal errors.

---

## Verification (whole feature)

- [ ] Run the full worker test suite: `.venv/bin/python -m pytest tests/test_worker.py -v` — all PASS.
- [ ] `grep -c "restart: on-failure:5" docker-compose.yml` returns `5`.
- [ ] `docker inspect` shows `on-failure:5` on all five containers.
- [ ] Worker container is `Up (healthy)`.

---

## Notes / deferred items

- **Import retry cadence (from spec open item):** the import tick is gated by `should_run_catch_up_tick` (~2h window). After a retryable failure the loop continues, but whether the *next* import attempt happens on the 60s backoff or waits ~2h depends on whether a failed import advances the gating timestamp. The worker survives either way. If during execution you observe a failed import deferring the retry by ~2h and that is undesirable, raise it for a follow-up — do NOT expand this plan's scope to change the gating logic without discussion.
- **Reboot auto-start:** intentionally not provided (`on-failure` does not auto-start after host/daemon reboot). After a Mac/Docker Desktop restart, run `docker compose up -d`.
