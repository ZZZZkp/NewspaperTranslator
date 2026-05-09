# Worker Error Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both worker roles survive transient orchestration failures with bounded retry and backoff, while still exiting immediately on fatal infrastructure errors.

**Architecture:** Keep task-level state transitions in `document_processing.py` unchanged, add narrowly scoped SQLite retry helpers around worker-critical database operations, and add explicit retryable-versus-fatal exception handling in `worker.py`. Use deterministic `unittest` coverage with injected callbacks and fake sleep/log functions so runtime behavior stays testable without long waits.

**Tech Stack:** Python 3, SQLite via `sqlite3`, `unittest`, existing structured JSON logging helper, `concurrent.futures.ThreadPoolExecutor`.

**Spec:** `docs/superpowers/specs/2026-05-09-worker-error-mechanism-design.md`

---

## File Map

**Modified:**
- `src/newspaper_translator/document_processing.py` — add a bounded SQLite retry helper plus retryable database classification; route worker-critical listing, claiming, and scheduler-run persistence through it.
- `src/newspaper_translator/worker.py` — add explicit worker loop exception types, fatal classification, loop backoff computation, structured runtime logging, and retryable/fatal boundaries for both worker roles.
- `tests/test_drain.py` — add focused tests proving SQLite lock/query retry behavior at the drain/tick boundary.
- `tests/test_worker.py` — add focused tests proving import/article loops back off on retryable failures, reset failure streak after recovery, and still raise on fatal failures.

**Optional modified during implementation if needed for small helper reuse only:**
- `tests/test_logging_utils.py` — only if extracting an assertion helper there is materially cleaner; otherwise keep all new logging assertions in `tests/test_worker.py`.

---

## Pre-flight

- [ ] **Step 0.1: Confirm the worker and drain entry points still match the plan**

```bash
cd /Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator
rg -n "def run_startup_maintenance|def run_article_worker_loop|def run_worker_loop" src/newspaper_translator/worker.py
rg -n "def create_scheduler_run|def finalize_scheduler_run|def get_latest_scheduler_run|def claim_document_processing_run|def claim_article_processing_run|def list_eligible_document_processing_runs|def list_eligible_article_processing_runs" src/newspaper_translator/document_processing.py
```

Expected: the function definitions are still present in the files listed above. If names moved, update the plan before implementation.

- [ ] **Step 0.2: Run the focused baseline suites**

```bash
./.venv/bin/python -m unittest tests.test_worker tests.test_drain -v 2>&1 | tail -20
```

Expected: current tests pass. If they do not, stop and resolve baseline breakage before Task 1.

---

## Task 1: Add explicit worker-loop error helpers and unit tests

**Files:**
- Modify: `src/newspaper_translator/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1.1: Write failing helper tests in `tests/test_worker.py`**

Append the following new test class near the bottom of `tests/test_worker.py`, above `if __name__ == "__main__":`:

```python
class WorkerErrorHelperTests(unittest.TestCase):
    def test_retryable_loop_backoff_caps_after_third_failure(self) -> None:
        from newspaper_translator.worker import _loop_retry_backoff_seconds

        self.assertEqual(_loop_retry_backoff_seconds(1), 5)
        self.assertEqual(_loop_retry_backoff_seconds(2), 15)
        self.assertEqual(_loop_retry_backoff_seconds(3), 60)
        self.assertEqual(_loop_retry_backoff_seconds(8), 60)

    def test_classifies_sqlite_locked_operational_error_as_retryable(self) -> None:
        import sqlite3

        from newspaper_translator.worker import _is_retryable_worker_loop_error

        error = sqlite3.OperationalError("database is locked")

        self.assertEqual(_is_retryable_worker_loop_error(error), True)

    def test_classifies_value_error_as_fatal(self) -> None:
        from newspaper_translator.worker import _is_fatal_worker_error

        self.assertEqual(_is_fatal_worker_error(ValueError("bad env")), True)

    def test_wraps_non_fatal_exception_as_retryable_loop_error(self) -> None:
        from newspaper_translator.worker import (
            RetryableWorkerLoopError,
            _raise_for_worker_loop_error,
        )

        with self.assertRaises(RetryableWorkerLoopError) as context:
            _raise_for_worker_loop_error(
                RuntimeError("temporary import failure"),
                stage="import_tick",
            )

        self.assertEqual(str(context.exception.__cause__), "temporary import failure")
        self.assertEqual(context.exception.stage, "import_tick")
```

Expected failure mode: `ImportError` or `AttributeError` because the helper names and exception classes do not exist yet.

- [ ] **Step 1.2: Run the focused helper tests and verify failure**

```bash
./.venv/bin/python -m unittest tests.test_worker.WorkerErrorHelperTests -v
```

Expected: FAIL with missing helper/function/class errors.

- [ ] **Step 1.3: Add the worker helper implementation in `src/newspaper_translator/worker.py`**

Insert the following code near the top of `src/newspaper_translator/worker.py`, after the imports and before `build_startup_report(...)`:

```python
import sqlite3


class RetryableWorkerLoopError(RuntimeError):
    def __init__(self, *, stage: str, cause: Exception):
        super().__init__(f"retryable worker loop failure during {stage}: {cause}")
        self.stage = stage
        self.cause = cause


class FatalWorkerError(RuntimeError):
    def __init__(self, *, stage: str, cause: Exception):
        super().__init__(f"fatal worker failure during {stage}: {cause}")
        self.stage = stage
        self.cause = cause


def _loop_retry_backoff_seconds(consecutive_failures: int) -> int:
    if consecutive_failures <= 1:
        return 5
    if consecutive_failures == 2:
        return 15
    return 60


def _is_retryable_worker_loop_error(exc: Exception) -> bool:
    if isinstance(exc, RetryableWorkerLoopError):
        return True
    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return "database is locked" in message or "database is busy" in message
    return False


def _is_fatal_worker_error(exc: Exception) -> bool:
    return isinstance(exc, (FatalWorkerError, ValueError, LookupError))


def _raise_for_worker_loop_error(exc: Exception, *, stage: str) -> None:
    if _is_fatal_worker_error(exc):
        raise FatalWorkerError(stage=stage, cause=exc) from exc
    raise RetryableWorkerLoopError(stage=stage, cause=exc) from exc
```

Keep these helpers private. They only exist to make loop behavior explicit and testable.

- [ ] **Step 1.4: Run the helper tests and verify they pass**

```bash
./.venv/bin/python -m unittest tests.test_worker.WorkerErrorHelperTests -v
```

Expected: PASS.

- [ ] **Step 1.5: Commit the helper slice**

```bash
git add src/newspaper_translator/worker.py tests/test_worker.py
git commit -m "feat: add worker loop error helpers"
```

---

## Task 2: Add bounded SQLite retries around worker-critical database operations

**Files:**
- Modify: `src/newspaper_translator/document_processing.py`
- Test: `tests/test_drain.py`

- [ ] **Step 2.1: Write a failing retry test for eligible-run listing**

Append this test method to `DrainTests` in `tests/test_drain.py`:

```python
    def test_document_processing_drain_retries_locked_database_read_once(self) -> None:
        self.assertIsNotNone(run_document_processing_drain)

        calls = {"count": 0}

        def flaky_list_eligible_document_processing_runs(*, database_url: str, limit: int):
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return [
                SimpleNamespace(document_key="message-1:attachment-1:hash-1")
            ] if calls["count"] == 2 else []

        with mock.patch.object(
            document_processing_module,
            "list_eligible_document_processing_runs",
            side_effect=flaky_list_eligible_document_processing_runs,
        ):
            with mock.patch.object(
                document_processing_module,
                "claim_document_processing_run",
                return_value=SimpleNamespace(document_key="message-1:attachment-1:hash-1"),
            ):
                drain_result = run_document_processing_drain(
                    database_url="sqlite:////tmp/app.db",
                    process_one_document=lambda **kwargs: SimpleNamespace(status="succeeded"),
                    document_limit=1,
                    scheduler_run_id="scheduler-run-1",
                )

        self.assertEqual(calls["count"], 3)
        self.assertEqual(drain_result.completed_count, 1)
        self.assertEqual(drain_result.failed_count, 0)
```

Add missing imports at the top of the file if needed:

```python
import sqlite3
from types import SimpleNamespace
```

Expected failure mode: the first `OperationalError` escapes `run_document_processing_drain(...)` and the test errors.

- [ ] **Step 2.2: Write a failing retry exhaustion test for scheduler-run lookup**

Append this second method to `DrainTests`:

```python
    def test_processing_tick_raises_operational_error_after_retry_exhaustion(self) -> None:
        self.assertIsNotNone(document_processing_module)

        attempts = {"count": 0}

        def always_locked(*, database_url: str, limit: int):
            attempts["count"] += 1
            raise sqlite3.OperationalError("database is locked")

        with mock.patch.object(
            document_processing_module,
            "list_eligible_document_processing_runs",
            side_effect=always_locked,
        ):
            with self.assertRaises(sqlite3.OperationalError):
                document_processing_module.run_processing_tick(
                    database_url="sqlite:////tmp/app.db",
                    trigger_type="processing",
                    process_one_document=lambda **kwargs: SimpleNamespace(status="succeeded"),
                    document_limit=1,
                )

        self.assertEqual(attempts["count"], 3)
```

Expected failure mode: currently the first raised `OperationalError` aborts the call, so `attempts["count"]` will be `1`.

- [ ] **Step 2.3: Run the focused drain tests and verify failure**

```bash
./.venv/bin/python -m unittest \
  tests.test_drain.DrainTests.test_document_processing_drain_retries_locked_database_read_once \
  tests.test_drain.DrainTests.test_processing_tick_raises_operational_error_after_retry_exhaustion \
  -v
```

Expected: one error and one failure, proving retries do not exist yet.

- [ ] **Step 2.4: Add the retry helpers in `src/newspaper_translator/document_processing.py`**

Insert the following helpers near the top of `src/newspaper_translator/document_processing.py`, after the dataclasses:

```python
DATABASE_RETRY_DELAYS_SECONDS = (0.2, 0.5, 1.0)


def _is_retryable_sqlite_error(exc: Exception) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


def _run_with_database_retries(callback, *, sleep_fn=time.sleep):
    attempts = len(DATABASE_RETRY_DELAYS_SECONDS)
    for attempt_index in range(attempts):
        try:
            return callback()
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable_sqlite_error(exc):
                raise
            if attempt_index == attempts - 1:
                raise
            sleep_fn(DATABASE_RETRY_DELAYS_SECONDS[attempt_index])
```

Add the import if missing:

```python
import time
```

- [ ] **Step 2.5: Route worker-critical database helpers through `_run_with_database_retries(...)`**

Update the database-heavy helpers in `src/newspaper_translator/document_processing.py` so the single SQLite call in each function is wrapped by `_run_with_database_retries(...)`:

- `create_scheduler_run(...)`
- `finalize_scheduler_run(...)`
- `get_latest_scheduler_run(...)`
- `claim_document_processing_run(...)`
- `claim_article_processing_run(...)`
- `list_eligible_document_processing_runs(...)`
- `list_eligible_article_processing_runs(...)`

Use this pattern in each function:

```python
    def _operation():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            rows = connection.execute(...).fetchall()
            connection.commit()
            return rows
        finally:
            connection.close()

    rows = _run_with_database_retries(_operation)
```

For read-only operations like `get_latest_scheduler_run(...)` and the `list_eligible_*` functions, omit the `commit()` call and just return the query result.

Do not broaden retry usage to unrelated helpers in this slice.

- [ ] **Step 2.6: Run the focused drain tests and verify they pass**

```bash
./.venv/bin/python -m unittest \
  tests.test_drain.DrainTests.test_document_processing_drain_retries_locked_database_read_once \
  tests.test_drain.DrainTests.test_processing_tick_raises_operational_error_after_retry_exhaustion \
  -v
```

Expected: PASS. The first test should survive one lock and finish successfully; the second should retry three times and then re-raise.

- [ ] **Step 2.7: Commit the database retry slice**

```bash
git add src/newspaper_translator/document_processing.py tests/test_drain.py
git commit -m "feat: retry transient sqlite worker operations"
```

---

## Task 3: Add retryable/fatal boundaries and backoff to the import worker loop

**Files:**
- Modify: `src/newspaper_translator/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 3.1: Write failing import-worker loop tests**

Append these methods to `WorkerRoleDispatchTests` in `tests/test_worker.py`:

```python
    def test_import_worker_loop_backs_off_after_retryable_processing_failure(self) -> None:
        calls: list[tuple[str, str | None]] = []
        sleep_calls: list[int] = []
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "import",
            "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        def failing_processing_tick():
            raise RuntimeError("temporary drain failure")

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-09T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=1,
            run_import_tick_fn=lambda *, trigger_type: calls.append(("import", trigger_type)) or "import-run-1",
            run_processing_tick_fn=failing_processing_tick,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-09T12:00:00",
            run_startup_maintenance_fn=lambda **kwargs: calls.append(("startup", kwargs["last_scheduler_run_started_at"])) or {},
        )

        self.assertEqual(calls, [("startup", "2026-05-09T12:00:00")])
        self.assertEqual(sleep_calls, [5])

    def test_import_worker_loop_resets_failure_streak_after_success(self) -> None:
        sleep_calls: list[int] = []
        processing_results = iter(
            [
                RuntimeError("temporary drain failure"),
                SimpleNamespace(did_work=False),
            ]
        )
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "import",
            "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        def processing_tick():
            result = next(processing_results)
            if isinstance(result, Exception):
                raise result
            return result

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-09T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=2,
            run_import_tick_fn=lambda *, trigger_type: "import-run-1",
            run_processing_tick_fn=processing_tick,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-09T12:00:00",
            run_startup_maintenance_fn=lambda **kwargs: {},
        )

        self.assertEqual(sleep_calls, [5, 60])

    def test_import_worker_loop_raises_on_fatal_processing_failure(self) -> None:
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "import",
        }

        with self.assertRaises(Exception):
            run_worker_loop(
                env=env,
                now_fn=lambda: "2026-05-09T12:00:00",
                sleep_fn=lambda seconds: None,
                max_loops=1,
                run_import_tick_fn=lambda *, trigger_type: "import-run-1",
                run_processing_tick_fn=lambda: (_ for _ in ()).throw(ValueError("bad env")),
                recover_stale_document_runs_fn=lambda: [],
                recover_stale_article_runs_fn=lambda: [],
                get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-09T12:00:00",
                run_startup_maintenance_fn=lambda **kwargs: {},
            )
```

Expected failure mode: current `run_worker_loop(...)` lets the runtime error escape, so the first two tests error instead of sleeping and continuing.

- [ ] **Step 3.2: Run the focused import-loop tests and verify failure**

```bash
./.venv/bin/python -m unittest \
  tests.test_worker.WorkerRoleDispatchTests.test_import_worker_loop_backs_off_after_retryable_processing_failure \
  tests.test_worker.WorkerRoleDispatchTests.test_import_worker_loop_resets_failure_streak_after_success \
  tests.test_worker.WorkerRoleDispatchTests.test_import_worker_loop_raises_on_fatal_processing_failure \
  -v
```

Expected: the retryable-failure tests fail because the exception escapes immediately.

- [ ] **Step 3.3: Implement import-loop backoff and classification**

Update `run_worker_loop(...)` in `src/newspaper_translator/worker.py` so the outer loop tracks `consecutive_loop_failures` and wraps the import and processing boundaries:

```python
    consecutive_loop_failures = 0
    while max_loops is None or loop_count < max_loops:
        try:
            if should_run_catch_up_tick(...):
                run_import_tick(trigger_type="interval")

            if not processing_running:
                processing_running = True
                try:
                    tick_result = run_processing_tick_callback()
                finally:
                    processing_running = False
                last_did_work = bool(getattr(tick_result, "did_work", False))
        except Exception as exc:  # noqa: BLE001
            if processing_running:
                processing_running = False
            _raise_for_worker_loop_error(exc, stage="import_worker_loop")
        else:
            if consecutive_loop_failures > 0:
                _emit_worker_loop_log(
                    event="worker.loop.recovered",
                    worker_role="import",
                    stage="import_worker_loop",
                    details={"consecutive_failures": consecutive_loop_failures},
                )
            consecutive_loop_failures = 0
            loop_count += 1
            sleep(active_poll_interval_seconds if last_did_work else idle_poll_interval_seconds)
            continue

        # retryable path
        consecutive_loop_failures += 1
        backoff_seconds = _loop_retry_backoff_seconds(consecutive_loop_failures)
        _emit_worker_loop_log(
            event="worker.loop.retryable_failure",
            worker_role="import",
            stage="import_worker_loop",
            details={
                "consecutive_failures": consecutive_loop_failures,
                "sleep_seconds": backoff_seconds,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        loop_count += 1
        sleep(backoff_seconds)
```

To make the above compile cleanly, add a small log helper to `worker.py`:

```python
def _emit_worker_loop_log(*, event: str, worker_role: str, stage: str, details: dict[str, object]) -> None:
    print(
        format_log_event(
            level="INFO" if event == "worker.loop.recovered" else "ERROR",
            event=event,
            service="worker",
            details={
                "worker_role": worker_role,
                "stage": stage,
                **details,
            },
        ),
        flush=True,
    )
```

Catch `RetryableWorkerLoopError` separately from `FatalWorkerError` so fatal errors are re-raised immediately after emitting `worker.loop.fatal_failure`.

- [ ] **Step 3.4: Run the focused import-loop tests and verify they pass**

```bash
./.venv/bin/python -m unittest \
  tests.test_worker.WorkerRoleDispatchTests.test_import_worker_loop_backs_off_after_retryable_processing_failure \
  tests.test_worker.WorkerRoleDispatchTests.test_import_worker_loop_resets_failure_streak_after_success \
  tests.test_worker.WorkerRoleDispatchTests.test_import_worker_loop_raises_on_fatal_processing_failure \
  -v
```

Expected: PASS.

- [ ] **Step 3.5: Commit the import worker loop slice**

```bash
git add src/newspaper_translator/worker.py tests/test_worker.py
git commit -m "feat: add import worker loop backoff"
```

---

## Task 4: Apply the same policy to the article worker loop and finish focused verification

**Files:**
- Modify: `src/newspaper_translator/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 4.1: Write failing article-worker loop tests**

Append these methods to `WorkerRoleDispatchTests` in `tests/test_worker.py`:

```python
    def test_article_worker_loop_backs_off_after_retryable_probe_failure(self) -> None:
        sleep_calls: list[int] = []
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "article",
            "ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS": "30",
        }

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-09T12:00:00",
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            max_loops=1,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_article_processing_tick_fn=lambda: SimpleNamespace(did_work=False),
            article_work_exists_fn=lambda: (_ for _ in ()).throw(RuntimeError("temporary probe failure")),
        )

        self.assertEqual(sleep_calls, [5])

    def test_article_worker_loop_raises_on_fatal_probe_failure(self) -> None:
        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
            "STORAGE_ROOT": "/tmp/newspaper-translator-data",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "WORKER_ROLE": "article",
        }

        with self.assertRaises(Exception):
            run_worker_loop(
                env=env,
                now_fn=lambda: "2026-05-09T12:00:00",
                sleep_fn=lambda seconds: None,
                max_loops=1,
                recover_stale_document_runs_fn=lambda: [],
                recover_stale_article_runs_fn=lambda: [],
                run_article_processing_tick_fn=lambda: SimpleNamespace(did_work=False),
                article_work_exists_fn=lambda: (_ for _ in ()).throw(ValueError("broken role config")),
            )
```

Expected failure mode: the retryable probe failure escapes instead of causing backoff.

- [ ] **Step 4.2: Run the focused article-loop tests and verify failure**

```bash
./.venv/bin/python -m unittest \
  tests.test_worker.WorkerRoleDispatchTests.test_article_worker_loop_backs_off_after_retryable_probe_failure \
  tests.test_worker.WorkerRoleDispatchTests.test_article_worker_loop_raises_on_fatal_probe_failure \
  -v
```

Expected: the first test errors because `RuntimeError("temporary probe failure")` is uncaught.

- [ ] **Step 4.3: Implement article-loop retryable/fatal handling**

Update `run_article_worker_loop(...)` in `src/newspaper_translator/worker.py` to mirror the import loop policy:

```python
    consecutive_loop_failures = 0
    while max_loops is None or loop_count < max_loops:
        try:
            if _work_exists():
                run_tick()
        except Exception as exc:  # noqa: BLE001
            try:
                _raise_for_worker_loop_error(exc, stage="article_worker_loop")
            except RetryableWorkerLoopError:
                consecutive_loop_failures += 1
                backoff_seconds = _loop_retry_backoff_seconds(consecutive_loop_failures)
                _emit_worker_loop_log(
                    event="worker.loop.retryable_failure",
                    worker_role="article",
                    stage="article_worker_loop",
                    details={
                        "consecutive_failures": consecutive_loop_failures,
                        "sleep_seconds": backoff_seconds,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                loop_count += 1
                sleep(backoff_seconds)
                continue
            except FatalWorkerError:
                _emit_worker_loop_log(
                    event="worker.loop.fatal_failure",
                    worker_role="article",
                    stage="article_worker_loop",
                    details={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                raise
        else:
            if consecutive_loop_failures > 0:
                _emit_worker_loop_log(
                    event="worker.loop.recovered",
                    worker_role="article",
                    stage="article_worker_loop",
                    details={"consecutive_failures": consecutive_loop_failures},
                )
            consecutive_loop_failures = 0
            loop_count += 1
            sleep(idle_poll_interval_seconds)
```

Keep the existing startup recovery call before the loop. If startup recovery itself raises, run it through the same fatal-versus-retryable classification logic rather than swallowing it silently.

- [ ] **Step 4.4: Run the full focused suites**

```bash
./.venv/bin/python -m unittest tests.test_worker tests.test_drain -v
```

Expected: PASS.

- [ ] **Step 4.5: Commit the article loop slice**

```bash
git add src/newspaper_translator/worker.py tests/test_worker.py tests/test_drain.py
git commit -m "feat: add article worker failure backoff"
```

---

## Task 5: Final verification and cleanup

**Files:**
- Modify only if a failing assertion exposed a naming mismatch during prior tasks.

- [ ] **Step 5.1: Run the broader regression slice**

```bash
./.venv/bin/python -m unittest \
  tests.test_worker \
  tests.test_drain \
  tests.test_database \
  tests.test_logging_utils \
  -v 2>&1 | tail -40
```

Expected: ends with `OK`.

- [ ] **Step 5.2: Inspect the final diff**

```bash
git diff --stat HEAD~3..HEAD
git status --short
```

Expected: the diff only touches the planned worker/drain test and runtime files, and `git status --short` is clean.

- [ ] **Step 5.3: Final integration commit if needed**

If the previous tasks already produced clean commits and there are no extra edits, skip this step. If there is still uncommitted cleanup, commit it with:

```bash
git add src/newspaper_translator/document_processing.py src/newspaper_translator/worker.py tests/test_drain.py tests/test_worker.py
git commit -m "test: cover worker error handling runtime"
```

---

## Spec Coverage Check

- Layered error ownership: Task 1 and Task 3 keep task-level failures separate from worker-loop failures.
- Bounded SQLite retry for worker-critical paths: Task 2.
- Retryable versus fatal loop classification: Task 1, Task 3, Task 4.
- Loop backoff and recovery reset: Task 3 and Task 4.
- Structured runtime logging for retryable/fatal/recovered loop states: Task 3 and Task 4.
- Shared behavior for import and article worker roles: Task 3 and Task 4.

## Placeholder Scan

- No `TODO`, `TBD`, or deferred “handle appropriately” language remains.
- Every code-changing step includes concrete code or exact functions to edit.
- Every validation step includes exact commands and expected outcomes.

## Type Consistency Check

- Runtime helper names are consistent across tasks: `_loop_retry_backoff_seconds`, `_is_retryable_worker_loop_error`, `_is_fatal_worker_error`, `_raise_for_worker_loop_error`, `_emit_worker_loop_log`.
- Exception names are consistent across tasks: `RetryableWorkerLoopError`, `FatalWorkerError`.
- Database retry helper names are consistent across tasks: `DATABASE_RETRY_DELAYS_SECONDS`, `_is_retryable_sqlite_error`, `_run_with_database_retries`.
