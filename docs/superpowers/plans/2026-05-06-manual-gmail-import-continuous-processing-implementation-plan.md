# Manual Gmail Import Continuous Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an operator-workbench button for immediate Gmail import, while splitting worker behavior so Gmail import stays on a 2-hour cadence and queued document/article processing runs continuously.

**Architecture:** Keep one worker process, but extract import-only and processing-only ticks from the current combined scheduler tick. The web API triggers import-only work, and the worker main loop separately schedules import catch-up and short-interval processing passes.

**Tech Stack:** Python stdlib WSGI backend, SQLite persistence, existing Gmail/MinerU/Gemini service modules, vanilla HTML/CSS/JavaScript frontend, unittest test suite.

---

## File Structure

- `src/newspaper_translator/document_processing.py`
  - Add `run_processing_tick(...)`.
  - Refactor `run_scheduler_tick(...)` to call import first, then processing.
  - Keep existing document/article selection, concurrency, status aggregation, and scheduler-run finalization semantics.

- `src/newspaper_translator/worker.py`
  - Add import-interval helpers and processing-loop helpers.
  - Keep stale recovery on startup.
  - Make `run_worker_loop(...)` call import on the 2-hour cadence and processing on the 60-second cadence.
  - Add builder functions for import-only and processing-only ticks from env.

- `src/newspaper_translator/web.py`
  - Add `POST /api/gmail/import`.
  - Wire it to the same Gmail import path used by the worker import loop.
  - Return import summary JSON or concise error JSON.

- `src/newspaper_translator/manage.py`
  - Update `process-pending-documents` to call `run_processing_tick(...)`.
  - Keep `scheduler-run-once` behavior compatible.

- `frontend/index.html`
  - Add a shared operator-workbench action row with `立即拉取邮件`.

- `frontend/app.js`
  - Add DOM bindings, click handler, fetch call, loading state, success/error summary, and list refresh behavior.

- `frontend/styles.css`
  - Add or reuse compact workbench action-row styles.

- Tests:
  - `tests/test_document_processing.py`
  - `tests/test_worker.py`
  - `tests/test_web.py`
  - `tests/test_frontend_static.py`

## Task 1: Extract Processing-Only Tick

**Files:**
- Modify: `src/newspaper_translator/document_processing.py`
- Test: `tests/test_document_processing.py`

- [ ] **Step 1: Write failing import and processing-only tests**

In `tests/test_document_processing.py`, update the guarded import block to import `run_processing_tick`:

```python
from newspaper_translator.document_processing import (
    create_article_processing_run,
    create_document_processing_run,
    create_scheduler_run,
    fail_article_processing_run,
    fail_document_processing_run,
    finalize_scheduler_run,
    get_article_processing_run,
    get_document_processing_run,
    get_latest_scheduler_run,
    get_scheduler_run,
    list_eligible_article_processing_runs,
    list_eligible_document_processing_runs,
    recover_stale_article_runs,
    recover_stale_document_runs,
    request_manual_article_retry,
    request_manual_document_retry,
    run_processing_tick,
    run_scheduler_tick,
    succeed_article_processing_run,
    succeed_document_processing_run,
)
```

In the `except ImportError` fallback, add:

```python
run_processing_tick = None
```

Add this test near the scheduler tick tests:

```python
def test_processing_tick_processes_documents_without_importing_gmail(self) -> None:
    self.assertIsNotNone(run_pending_migrations)
    self.assertIsNotNone(create_document_processing_run)
    self.assertIsNotNone(run_processing_tick)
    self.assertIsNotNone(get_scheduler_run)

    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = pathlib.Path(temp_dir) / "app.db"
        database_url = f"sqlite:///{database_path}"
        run_pending_migrations(database_url)
        document_key = self._insert_document(
            database_path,
            "message-1:attachment-1:hash-1",
        )
        create_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        )
        processed_document_keys: list[str] = []

        def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
            processed_document_keys.append(document_key)
            return SimpleNamespace(
                document_key=document_key,
                status="succeeded",
                scheduler_run_id=scheduler_run_id,
                locked_by=locked_by,
            )

        scheduler_run = run_processing_tick(
            database_url=database_url,
            trigger_type="processing",
            process_one_document=process_one_document,
            document_limit=10,
        )
        stored_scheduler_run = get_scheduler_run(
            database_url=database_url,
            scheduler_run_id=scheduler_run.scheduler_run_id,
        )

    self.assertEqual(processed_document_keys, [document_key])
    self.assertEqual(stored_scheduler_run.import_run_id, None)
    self.assertEqual(stored_scheduler_run.selected_document_count, 1)
    self.assertEqual(stored_scheduler_run.completed_document_count, 1)
    self.assertEqual(stored_scheduler_run.failed_document_count, 0)
    self.assertEqual(stored_scheduler_run.status, "succeeded")
```

Add the order test:

```python
def test_processing_tick_processes_documents_before_articles(self) -> None:
    self.assertIsNotNone(run_pending_migrations)
    self.assertIsNotNone(create_document_processing_run)
    self.assertIsNotNone(create_article_processing_run)
    self.assertIsNotNone(run_processing_tick)
    self.assertIsNotNone(list_latest_document_articles)

    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = pathlib.Path(temp_dir) / "app.db"
        database_url = f"sqlite:///{database_path}"
        run_pending_migrations(database_url)
        document_key = self._insert_document(
            database_path,
            "message-1:attachment-1:hash-1",
        )
        create_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        )
        self._persist_parsed_document_articles(
            database_url=database_url,
            document_key=document_key,
        )
        article = list_latest_document_articles(
            database_url=database_url,
            document_key=document_key,
        )[0]
        create_article_processing_run(
            database_url=database_url,
            article_id=article.article_id,
        )
        events: list[str] = []

        def process_one_document(*, document_key: str, scheduler_run_id: str, locked_by: str):
            events.append(f"document:{document_key}")
            return SimpleNamespace(status="succeeded")

        def process_one_article(*, article_key: str, locked_by: str):
            events.append(f"article:{article_key}")
            return succeed_article_processing_run(
                database_url=database_url,
                article_key=article_key,
                last_success_input_hash=f"hash:{locked_by}",
            )

        run_processing_tick(
            database_url=database_url,
            trigger_type="processing",
            process_one_document=process_one_document,
            document_limit=10,
            process_one_article=process_one_article,
            article_limit=10,
        )

    self.assertEqual(events, [f"document:{document_key}", f"article:{article.article_key}"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_document_processing.py::DocumentProcessingTests::test_processing_tick_processes_documents_without_importing_gmail -q
./.venv/bin/python -m pytest tests/test_document_processing.py::DocumentProcessingTests::test_processing_tick_processes_documents_before_articles -q
```

Expected: both fail with an import error or `run_processing_tick` being `None`.

- [ ] **Step 3: Implement `run_processing_tick`**

In `src/newspaper_translator/document_processing.py`, extract the processing body from `run_scheduler_tick` into this new function:

```python
def run_processing_tick(
    *,
    database_url: str,
    trigger_type: str,
    process_one_document,
    document_limit: int,
    process_one_article=None,
    article_limit: int = 0,
    import_run_id: str | None = None,
    locked_by_prefix: str = "scheduler-worker",
    article_locked_by_prefix: str = "article-worker",
    log_event=None,
) -> SchedulerRun:
    scheduler_run = create_scheduler_run(
        database_url=database_url,
        trigger_type=trigger_type,
    )
    _log_event(
        log_event,
        event="scheduler.processing.started",
        details={
            "scheduler_run_id": scheduler_run.scheduler_run_id,
            "trigger_type": trigger_type,
        },
    )
    eligible_runs = list_eligible_document_processing_runs(
        database_url=database_url,
        limit=document_limit,
    )
    eligible_article_runs = (
        list_eligible_article_processing_runs(
            database_url=database_url,
            limit=article_limit,
        )
        if process_one_article is not None and article_limit > 0
        else []
    )

    completed_document_count = 0
    failed_document_count = 0
    error_messages: list[str] = []
    max_workers = max(1, len(eligible_runs))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_document_key = {
            executor.submit(
                process_one_document,
                document_key=eligible_run.document_key,
                scheduler_run_id=scheduler_run.scheduler_run_id,
                locked_by=f"{locked_by_prefix}-{index}",
            ): eligible_run.document_key
            for index, eligible_run in enumerate(eligible_runs, start=1)
        }
        for future in as_completed(future_to_document_key):
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                failed_document_count += 1
                error_messages.append(str(exc))
                continue

            if getattr(result, "status", "") == "succeeded":
                completed_document_count += 1
            else:
                failed_document_count += 1

    max_article_workers = max(1, len(eligible_article_runs))
    with ThreadPoolExecutor(max_workers=max_article_workers) as executor:
        future_to_article_key = {
            executor.submit(
                process_one_article,
                article_key=eligible_run.article_key,
                locked_by=f"{article_locked_by_prefix}-{index}",
            ): eligible_run.article_key
            for index, eligible_run in enumerate(eligible_article_runs, start=1)
        }
        for future in as_completed(future_to_article_key):
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                failed_document_count += 1
                error_messages.append(str(exc))
                continue

            if getattr(result, "status", "") == "succeeded":
                completed_document_count += 1
            else:
                failed_document_count += 1

    final_status = "succeeded"
    if failed_document_count and completed_document_count:
        final_status = "partial"
    elif failed_document_count:
        final_status = "failed"

    finalize_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
        status=final_status,
        import_run_id=import_run_id,
        selected_document_count=len(eligible_runs) + len(eligible_article_runs),
        completed_document_count=completed_document_count,
        failed_document_count=failed_document_count,
        error_message="; ".join(error_messages) if error_messages else None,
    )
    finalized_run = get_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
    )
    _log_event(
        log_event,
        event="scheduler.processing.finished",
        details={
            "scheduler_run_id": finalized_run.scheduler_run_id,
            "status": finalized_run.status,
            "selected_document_count": finalized_run.selected_document_count,
            "completed_document_count": finalized_run.completed_document_count,
            "failed_document_count": finalized_run.failed_document_count,
        },
    )
    return finalized_run
```

Then reduce `run_scheduler_tick` so it does import and delegates:

```python
def run_scheduler_tick(
    *,
    database_url: str,
    trigger_type: str,
    import_documents,
    process_one_document,
    document_limit: int,
    process_one_article=None,
    article_limit: int = 0,
    locked_by_prefix: str = "scheduler-worker",
    article_locked_by_prefix: str = "article-worker",
    log_event=None,
) -> SchedulerRun:
    _log_event(
        log_event,
        event="scheduler.tick.started",
        details={"trigger_type": trigger_type},
    )
    _log_event(
        log_event,
        event="scheduler.import.started",
        details={"trigger_type": trigger_type},
    )
    import_result = import_documents()
    import_run_id = getattr(import_result, "run_id", None)
    _log_event(
        log_event,
        event="scheduler.import.finished",
        details={"trigger_type": trigger_type, "import_run_id": import_run_id},
    )
    finalized_run = run_processing_tick(
        database_url=database_url,
        trigger_type=trigger_type,
        process_one_document=process_one_document,
        document_limit=document_limit,
        process_one_article=process_one_article,
        article_limit=article_limit,
        import_run_id=import_run_id,
        locked_by_prefix=locked_by_prefix,
        article_locked_by_prefix=article_locked_by_prefix,
        log_event=log_event,
    )
    _log_event(
        log_event,
        event="scheduler.tick.finished",
        details={
            "scheduler_run_id": finalized_run.scheduler_run_id,
            "status": finalized_run.status,
            "selected_document_count": finalized_run.selected_document_count,
            "completed_document_count": finalized_run.completed_document_count,
            "failed_document_count": finalized_run.failed_document_count,
        },
    )
    return finalized_run
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_document_processing.py::DocumentProcessingTests::test_processing_tick_processes_documents_without_importing_gmail -q
./.venv/bin/python -m pytest tests/test_document_processing.py::DocumentProcessingTests::test_processing_tick_processes_documents_before_articles -q
./.venv/bin/python -m pytest tests/test_document_processing.py::DocumentProcessingTests::test_scheduler_tick_can_continue_retryable_documents_when_gmail_import_finds_nothing_new -q
```

Expected: all pass.

- [ ] **Step 5: Adjust scheduler lifecycle log test**

The existing `test_scheduler_tick_emits_scheduler_and_import_lifecycle_logs` should expect the new processing lifecycle events:

```python
self.assertEqual(
    log_events,
    [
        "scheduler.tick.started",
        "scheduler.import.started",
        "scheduler.import.finished",
        "scheduler.processing.started",
        "scheduler.processing.finished",
        "scheduler.tick.finished",
    ],
)
```

- [ ] **Step 6: Run document processing suite**

Run:

```bash
./.venv/bin/python -m pytest tests/test_document_processing.py -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/newspaper_translator/document_processing.py tests/test_document_processing.py
git commit -m "Refactor processing tick"
```

## Task 2: Split Worker Import And Processing Scheduling

**Files:**
- Modify: `src/newspaper_translator/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests for separate loops**

In `tests/test_worker.py`, update the import block to include new helpers:

```python
from newspaper_translator.worker import (
    build_process_one_article_from_env,
    build_process_one_document_from_env,
    build_run_import_tick_from_env,
    build_run_processing_tick_from_env,
    build_run_scheduler_tick_from_env,
    build_startup_log_line,
    build_startup_report,
    run_startup_maintenance,
    run_worker_loop,
    should_run_catch_up_tick,
)
```

Add fallbacks in `except ImportError`:

```python
build_run_import_tick_from_env = None
build_run_processing_tick_from_env = None
```

Add this test:

```python
def test_worker_loop_runs_processing_each_poll_without_overdue_import(self) -> None:
    self.assertIsNotNone(run_worker_loop)

    env = {
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
        "STORAGE_ROOT": "/tmp/newspaper-translator-data",
        "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
        "GMAIL_IMPORT_INTERVAL_SECONDS": "7200",
        "PROCESSING_POLL_INTERVAL_SECONDS": "60",
    }
    now_values = iter(["2026-05-06T12:00:00"])
    import_started_values = iter(["2026-05-06T11:30:00"])
    calls: list[tuple[str, str | None]] = []
    sleep_calls: list[int] = []

    def fake_startup_maintenance(**kwargs):
        calls.append(("startup", kwargs["last_scheduler_run_started_at"]))
        return {
            "recovered_document_keys": [],
            "recovered_article_keys": [],
            "catch_up_triggered": False,
            "scheduler_run_id": None,
        }

    def fake_get_last_started_at(*, database_url: str) -> str | None:
        self.assertEqual(database_url, "sqlite:////tmp/newspaper-translator.db")
        return next(import_started_values)

    def fake_processing_tick() -> str:
        calls.append(("processing", None))
        return "processing-run-1"

    def fake_import_tick(*, trigger_type: str) -> str:
        calls.append(("import", trigger_type))
        return "import-run-1"

    run_worker_loop(
        env=env,
        now_fn=lambda: next(now_values),
        sleep_fn=lambda seconds: sleep_calls.append(seconds),
        max_loops=1,
        run_startup_maintenance_fn=fake_startup_maintenance,
        get_last_scheduler_run_started_at_fn=fake_get_last_started_at,
        recover_stale_document_runs_fn=lambda: [],
        recover_stale_article_runs_fn=lambda: [],
        run_import_tick_fn=fake_import_tick,
        run_processing_tick_fn=fake_processing_tick,
    )

    self.assertEqual(calls, [("startup", "2026-05-06T11:30:00"), ("processing", None)])
    self.assertEqual(sleep_calls, [60])
```

Add this test:

```python
def test_worker_loop_runs_import_when_import_interval_is_overdue(self) -> None:
    self.assertIsNotNone(run_worker_loop)

    env = {
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite:////tmp/newspaper-translator.db",
        "STORAGE_ROOT": "/tmp/newspaper-translator-data",
        "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
        "GMAIL_IMPORT_INTERVAL_SECONDS": "7200",
        "PROCESSING_POLL_INTERVAL_SECONDS": "60",
    }
    calls: list[tuple[str, str | None]] = []

    run_worker_loop(
        env=env,
        now_fn=lambda: "2026-05-06T12:31:00",
        sleep_fn=lambda seconds: None,
        max_loops=1,
        run_startup_maintenance_fn=lambda **kwargs: calls.append(("startup", kwargs["last_scheduler_run_started_at"])),
        get_last_scheduler_run_started_at_fn=lambda *, database_url: "2026-05-06T10:30:00",
        recover_stale_document_runs_fn=lambda: [],
        recover_stale_article_runs_fn=lambda: [],
        run_import_tick_fn=lambda *, trigger_type: calls.append(("import", trigger_type)) or "import-run-1",
        run_processing_tick_fn=lambda: calls.append(("processing", None)) or "processing-run-1",
    )

    self.assertEqual(
        calls,
        [
            ("startup", "2026-05-06T10:30:00"),
            ("import", "interval"),
            ("processing", None),
        ],
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_worker.py::WorkerStartupTests::test_worker_loop_runs_processing_each_poll_without_overdue_import -q
./.venv/bin/python -m pytest tests/test_worker.py::WorkerStartupTests::test_worker_loop_runs_import_when_import_interval_is_overdue -q
```

Expected: fail because `run_worker_loop` does not accept `run_import_tick_fn` or `run_processing_tick_fn`.

- [ ] **Step 3: Add worker builders**

In `src/newspaper_translator/worker.py`, import `run_processing_tick`:

```python
from newspaper_translator.document_processing import (
    get_latest_scheduler_run,
    process_article_processing_run,
    process_document,
    recover_stale_article_runs,
    recover_stale_document_runs,
    run_processing_tick,
    run_scheduler_tick,
)
```

Add:

```python
def build_run_import_tick_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)

    def run_import_tick(*, trigger_type: str) -> str:
        summary = import_from_gmail(
            config_path=Path(app_settings.gmail_config_path),
            storage_root=Path(app_settings.storage_root),
            database_url=app_settings.database_url,
        )
        return getattr(summary, "run_id", "")

    return run_import_tick


def build_run_processing_tick_from_env(env: dict[str, str]):
    app_settings = AppSettings.from_env(env)
    document_limit = _read_int_setting(
        env,
        "DOCUMENT_WORKER_CONCURRENCY",
        default=2,
    )
    article_limit = _read_int_setting(
        env,
        "ARTICLE_WORKER_CONCURRENCY",
        default=document_limit,
    )
    process_one_document = build_process_one_document_from_env(env)
    process_one_article = build_process_one_article_from_env(env)

    def run_tick() -> str:
        scheduler_run = run_processing_tick(
            database_url=app_settings.database_url,
            trigger_type="processing",
            process_one_document=process_one_document,
            document_limit=document_limit,
            process_one_article=process_one_article,
            article_limit=article_limit,
        )
        return scheduler_run.scheduler_run_id

    return run_tick
```

- [ ] **Step 4: Update worker loop signature and scheduling**

Change `run_worker_loop(...)` signature to accept:

```python
run_import_tick_fn=None,
run_processing_tick_fn=None,
```

Inside `run_worker_loop`, replace scheduler interval reads with:

```python
import_interval_seconds = _read_int_setting(
    env,
    "GMAIL_IMPORT_INTERVAL_SECONDS",
    default=_read_int_setting(env, "SCHEDULER_INTERVAL_SECONDS", default=7200),
)
processing_poll_interval_seconds = _read_int_setting(
    env,
    "PROCESSING_POLL_INTERVAL_SECONDS",
    default=_read_int_setting(env, "WORKER_POLL_INTERVAL_SECONDS", default=60),
)
```

Use import and processing callbacks:

```python
run_import_tick = run_import_tick_fn or build_run_import_tick_from_env(env)
run_processing_tick_callback = run_processing_tick_fn or build_run_processing_tick_from_env(env)
```

Call startup maintenance with the import callback:

```python
run_startup_maintenance_fn(
    last_scheduler_run_started_at=get_last_scheduler_run_started_at_fn(
        database_url=app_settings.database_url,
    ),
    now=now(),
    interval_seconds=import_interval_seconds,
    recover_stale_document_runs=recover,
    recover_stale_article_runs=recover_articles,
    run_scheduler_tick=run_import_tick,
)
```

Use the split loop body:

```python
loop_count = 0
processing_running = False
while max_loops is None or loop_count < max_loops:
    sleep(processing_poll_interval_seconds)
    if should_run_catch_up_tick(
        last_scheduler_run_started_at=get_last_scheduler_run_started_at_fn(
            database_url=app_settings.database_url,
        ),
        now=now(),
        interval_seconds=import_interval_seconds,
    ):
        run_import_tick(trigger_type="interval")

    if not processing_running:
        processing_running = True
        try:
            run_processing_tick_callback()
        finally:
            processing_running = False
    loop_count += 1
```

- [ ] **Step 5: Update existing worker test expectations**

Rename or update `test_worker_loop_runs_periodic_tick_when_scheduler_becomes_overdue` so it expects both import and processing calls. The old fake `run_scheduler_tick_fn` argument should become `run_import_tick_fn`, and add:

```python
run_processing_tick_fn=lambda: calls.append(("processing", None)) or "processing-run-1",
recover_stale_article_runs_fn=lambda: [],
```

Expected calls:

```python
self.assertEqual(
    calls,
    [
        ("startup", "2026-04-28T10:30:00"),
        ("import", "interval"),
        ("processing", None),
    ],
)
```

- [ ] **Step 6: Run worker tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_worker.py -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/newspaper_translator/worker.py tests/test_worker.py
git commit -m "Split worker import and processing loops"
```

## Task 3: Add Manual Gmail Import API

**Files:**
- Modify: `src/newspaper_translator/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing web API tests**

In `tests/test_web.py`, add imports:

```python
from types import SimpleNamespace
from unittest.mock import patch
```

Add this test in the web endpoint test class:

```python
def test_manual_gmail_import_endpoint_returns_import_summary(self) -> None:
    self.assertIsNotNone(create_app)

    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = pathlib.Path(temp_dir) / "app.db"
        database_url = f"sqlite:///{database_path}"
        run_pending_migrations(database_url)
        app = create_app(
            {
                "APP_ENV": "test",
                "DATABASE_URL": database_url,
                "STORAGE_ROOT": temp_dir,
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            }
        )

        with patch("newspaper_translator.web.import_from_gmail") as import_from_gmail:
            import_from_gmail.return_value = SimpleNamespace(
                run_id="import-run-1",
                status="succeeded",
                fetched_message_count=25,
                imported_attachment_count=3,
                created_document_count=2,
                skipped_document_count=1,
            )

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/gmail/import",
                method="POST",
            )

    payload = json.loads(body.decode("utf-8"))

    self.assertEqual(status, "200 OK")
    self.assertEqual(payload["import_run"]["run_id"], "import-run-1")
    self.assertEqual(payload["import_run"]["created_document_count"], 2)
    self.assertEqual(import_from_gmail.call_args.kwargs["config_path"], pathlib.Path("/tmp/gmail-config.json"))
    self.assertEqual(import_from_gmail.call_args.kwargs["storage_root"], pathlib.Path(temp_dir))
    self.assertEqual(import_from_gmail.call_args.kwargs["database_url"], database_url)
```

Add failure test:

```python
def test_manual_gmail_import_endpoint_returns_error_when_import_fails(self) -> None:
    self.assertIsNotNone(create_app)

    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = pathlib.Path(temp_dir) / "app.db"
        database_url = f"sqlite:///{database_path}"
        run_pending_migrations(database_url)
        app = create_app(
            {
                "APP_ENV": "test",
                "DATABASE_URL": database_url,
                "STORAGE_ROOT": temp_dir,
                "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            }
        )

        with patch("newspaper_translator.web.import_from_gmail") as import_from_gmail:
            import_from_gmail.side_effect = RuntimeError("gmail unavailable")

            status, _, body = _perform_wsgi_request(
                app,
                path="/api/gmail/import",
                method="POST",
            )

    payload = json.loads(body.decode("utf-8"))

    self.assertEqual(status, "500 Internal Server Error")
    self.assertEqual(payload["status"], "gmail_import_failed")
    self.assertIn("gmail unavailable", payload["error"])
```

If `_perform_wsgi_request` does not accept `method`, update its signature near the bottom of the file:

```python
def _perform_wsgi_request(app, *, path: str, query_string: str = "", method: str = "GET"):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        app(
            {
                "PATH_INFO": path,
                "QUERY_STRING": query_string,
                "REQUEST_METHOD": method,
            },
            start_response,
        )
    )
    return captured["status"], captured["headers"], body
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_web.py::WebHealthEndpointTests::test_manual_gmail_import_endpoint_returns_import_summary -q
./.venv/bin/python -m pytest tests/test_web.py::WebHealthEndpointTests::test_manual_gmail_import_endpoint_returns_error_when_import_fails -q
```

Expected: fail with 404 or missing `import_from_gmail` patch target.

- [ ] **Step 3: Implement API**

In `src/newspaper_translator/web.py`, add imports:

```python
from newspaper_translator.gmail import import_from_gmail
```

Inside `create_app`, add:

```python
storage_root = env["STORAGE_ROOT"]
gmail_config_path = env["GMAIL_CONFIG_PATH"]
```

Before the article APIs, add:

```python
        if path == "/api/gmail/import":
            if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
                return _json_response(
                    start_response,
                    "405 Method Not Allowed",
                    {"status": "method_not_allowed"},
                )
            try:
                import_summary = import_from_gmail(
                    config_path=Path(gmail_config_path),
                    storage_root=Path(storage_root),
                    database_url=database_url,
                )
            except Exception as exc:  # noqa: BLE001
                return _json_response(
                    start_response,
                    "500 Internal Server Error",
                    {
                        "status": "gmail_import_failed",
                        "error": str(exc),
                    },
                )
            return _json_response(
                start_response,
                "200 OK",
                {"import_run": _to_jsonable(import_summary)},
            )
```

- [ ] **Step 4: Run web tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_web.py::WebHealthEndpointTests::test_manual_gmail_import_endpoint_returns_import_summary -q
./.venv/bin/python -m pytest tests/test_web.py::WebHealthEndpointTests::test_manual_gmail_import_endpoint_returns_error_when_import_fails -q
./.venv/bin/python -m pytest tests/test_web.py -q
```

Expected: pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/newspaper_translator/web.py tests/test_web.py
git commit -m "Add manual Gmail import API"
```

## Task 4: Update CLI Processing Command

**Files:**
- Modify: `src/newspaper_translator/manage.py`
- Test: `tests/test_manage.py`

- [ ] **Step 1: Write failing CLI test**

In `tests/test_manage.py`, add or update a test for `process-pending-documents`:

```python
def test_process_pending_documents_uses_processing_tick_without_gmail_import(self) -> None:
    self.assertIsNotNone(run_cli)

    with patch("newspaper_translator.manage.build_process_one_document_from_env") as build_document:
        with patch("newspaper_translator.manage.build_process_one_article_from_env") as build_article:
            with patch("newspaper_translator.manage.run_processing_tick") as run_processing_tick:
                build_document.return_value = lambda **kwargs: None
                build_article.return_value = lambda **kwargs: None
                run_processing_tick.return_value = SimpleNamespace(
                    scheduler_run_id="processing-run-1",
                    status="succeeded",
                    trigger_type="processing",
                )

                exit_code, output = run_cli(
                    [
                        "process-pending-documents",
                        "--database-url",
                        "sqlite:////tmp/newspaper-translator.db",
                    ]
                )

    payload = json.loads(output)

    self.assertEqual(exit_code, 0)
    self.assertEqual(payload["scheduler_run_id"], "processing-run-1")
    self.assertEqual(run_processing_tick.call_args.kwargs["trigger_type"], "processing")
    self.assertNotIn("import_documents", run_processing_tick.call_args.kwargs)
```

Ensure `SimpleNamespace` and `patch` are imported in that file:

```python
from types import SimpleNamespace
from unittest.mock import patch
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_manage.py::ManagementCommandTests::test_process_pending_documents_uses_processing_tick_without_gmail_import -q
```

Expected: fail because `manage.py` still calls `run_scheduler_tick`.

- [ ] **Step 3: Implement CLI change**

In `src/newspaper_translator/manage.py`, import worker article builder and processing tick:

```python
from newspaper_translator.document_processing import (
    get_article_processing_run,
    get_document_processing_run,
    request_manual_article_retry,
    request_manual_document_retry,
    run_processing_tick,
    run_scheduler_tick,
)
from newspaper_translator.worker import (
    build_process_one_article_from_env,
    build_process_one_document_from_env,
    build_run_scheduler_tick_from_env,
)
```

Replace `run_process_pending_documents_from_env` with:

```python
def run_process_pending_documents_from_env(env: dict[str, str]):
    resolved_env = dict(os.environ)
    resolved_env.update(env)
    database_url = resolved_env["DATABASE_URL"]
    document_limit = _read_int_setting(
        resolved_env,
        "DOCUMENT_WORKER_CONCURRENCY",
        default=2,
    )
    article_limit = _read_int_setting(
        resolved_env,
        "ARTICLE_WORKER_CONCURRENCY",
        default=document_limit,
    )
    process_one_document = build_process_one_document_from_env(resolved_env)
    process_one_article = build_process_one_article_from_env(resolved_env)

    return run_processing_tick(
        database_url=database_url,
        trigger_type="processing",
        process_one_document=process_one_document,
        document_limit=document_limit,
        process_one_article=process_one_article,
        article_limit=article_limit,
    )
```

- [ ] **Step 4: Run manage tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_manage.py -q
```

Expected: pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/newspaper_translator/manage.py tests/test_manage.py
git commit -m "Use processing tick for pending CLI"
```

## Task 5: Add Operator Workbench Gmail Import Button

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_static.py`

- [ ] **Step 1: Write failing frontend static tests**

In `tests/test_frontend_static.py`, add:

```python
def test_operator_workbench_has_manual_gmail_import_button(self) -> None:
    html = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    self.assertIn('id="manual-gmail-import-button"', html)
    self.assertIn("立即拉取邮件", html)
    self.assertIn('id="manual-gmail-import-summary"', html)


def test_frontend_calls_manual_gmail_import_api(self) -> None:
    app_js = (PROJECT_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    self.assertIn('"/api/gmail/import"', app_js)
    self.assertIn("requestManualGmailImport", app_js)
    self.assertIn("manualGmailImportButton.disabled = true", app_js)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/test_frontend_static.py::FrontendStaticTests::test_operator_workbench_has_manual_gmail_import_button -q
./.venv/bin/python -m pytest tests/test_frontend_static.py::FrontendStaticTests::test_frontend_calls_manual_gmail_import_api -q
```

Expected: fail because button and JS handler do not exist.

- [ ] **Step 3: Add HTML button**

In `frontend/index.html`, add this shared workbench action block before `document-processing-section`:

```html
          <section id="operator-actions-section" class="panel hidden">
            <div class="section-heading">
              <div>
                <p class="eyebrow">Operator Actions</p>
                <h2>处理工作台</h2>
              </div>
              <div class="button-row">
                <button id="manual-gmail-import-button" type="button">立即拉取邮件</button>
              </div>
            </div>
            <p id="manual-gmail-import-summary" class="meta-copy">后台会自动处理已入队的文档和文章。</p>
          </section>
```

- [ ] **Step 4: Wire DOM bindings and visibility**

Near the top of `frontend/app.js`, add:

```javascript
const operatorActionsSection = document.querySelector("#operator-actions-section");
const manualGmailImportButton = document.querySelector("#manual-gmail-import-button");
const manualGmailImportSummary = document.querySelector("#manual-gmail-import-summary");
```

Where dashboard sections are shown, hide the operator actions:

```javascript
operatorActionsSection.classList.add("hidden");
```

In `showDocumentProcessingPage()` and `showArticleProcessingPage()`, show it:

```javascript
operatorActionsSection.classList.remove("hidden");
```

- [ ] **Step 5: Add frontend request handler**

In `frontend/app.js`, add:

```javascript
async function requestManualGmailImport() {
  manualGmailImportButton.disabled = true;
  manualGmailImportSummary.textContent = "正在拉取邮件...";
  setStatus("正在拉取邮件...");
  try {
    const payload = await fetchJson("/api/gmail/import", { method: "POST" });
    const run = payload.import_run || {};
    const createdCount = run.created_document_count || 0;
    const fetchedCount = run.fetched_message_count || 0;
    const importedCount = run.imported_attachment_count || 0;
    if (createdCount > 0) {
      manualGmailImportSummary.textContent =
        `已检查 ${fetchedCount} 封邮件，新增 ${createdCount} 个文档，导入 ${importedCount} 个附件。后台处理会自动接手。`;
    } else {
      manualGmailImportSummary.textContent =
        `已检查 ${fetchedCount} 封邮件，没有新增文档。后台会继续处理已有队列。`;
    }
    if (!documentProcessingSection.classList.contains("hidden")) {
      await loadDocumentProcessing();
    } else if (!articleProcessingSection.classList.contains("hidden")) {
      await loadArticleProcessing();
    }
    setStatus("邮件拉取完成。");
  } catch (error) {
    manualGmailImportSummary.textContent = `邮件拉取失败：${error.message}`;
    setStatus(`邮件拉取失败：${error.message}`);
  } finally {
    manualGmailImportButton.disabled = false;
  }
}
```

Near existing event listeners, add:

```javascript
manualGmailImportButton.addEventListener("click", () => {
  requestManualGmailImport();
});
```

- [ ] **Step 6: Add minimal CSS**

In `frontend/styles.css`, add:

```css
#operator-actions-section {
  margin-bottom: 16px;
}

#manual-gmail-import-summary {
  margin-top: 10px;
}
```

- [ ] **Step 7: Run frontend static tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_frontend_static.py -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_static.py
git commit -m "Add manual Gmail import button"
```

## Task 6: End-To-End Verification

**Files:**
- No planned source changes unless verification finds a defect.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_document_processing.py tests/test_worker.py tests/test_web.py tests/test_manage.py tests/test_frontend_static.py -q
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
./.venv/bin/python -m pytest tests -q
```

Expected: pass. If network-backed tests are skipped or require credentials, record the exact skip/failure reason before proceeding.

- [ ] **Step 3: Start local stack if frontend verification is needed**

If Docker is already the normal project runtime, run:

```bash
docker compose up -d web frontend worker
```

Expected: services start without recreating unrelated state.

- [ ] **Step 4: Smoke-test API**

Against the local web service port, run:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/gmail/import
```

Expected: JSON with `import_run` on configured Gmail environments, or a JSON `gmail_import_failed` error if credentials/network are unavailable. A credential/network failure is acceptable in local smoke only if unit tests passed and the response shape is correct.

- [ ] **Step 5: Browser smoke-test frontend**

Open the frontend locally and verify:

- The processing workbench shows `立即拉取邮件`.
- Clicking it disables the button while the request is pending.
- Success or failure message appears in `manual-gmail-import-summary`.
- The current processing list remains usable after the request.

- [ ] **Step 6: Final commit for verification fixes**

If verification required code/test fixes, commit them:

```bash
git add src/newspaper_translator/document_processing.py src/newspaper_translator/worker.py src/newspaper_translator/web.py src/newspaper_translator/manage.py frontend/index.html frontend/app.js frontend/styles.css tests/test_document_processing.py tests/test_worker.py tests/test_web.py tests/test_manage.py tests/test_frontend_static.py
git commit -m "Verify manual import processing flow"
```

If no fixes were required, do not create an empty commit.

## Self-Review Notes

- Spec coverage: Tasks cover backend split (`run_processing_tick`, worker loops), manual Gmail API, frontend operator button, CLI compatibility, error responses, and verification.
- Scope: The plan keeps one worker process and does not add external queues or new containers.
- Type consistency: `run_processing_tick(...)` returns `SchedulerRun`; worker import tick returns a run id string; web API returns `{"import_run": ...}`.
- Known risk: `scheduler_runs` still records processing-only runs. This is intentional for this slice to avoid a migration; code names distinguish import and processing behavior.
