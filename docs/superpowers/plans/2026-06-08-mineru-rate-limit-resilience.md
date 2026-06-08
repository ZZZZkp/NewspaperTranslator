# MinerU Rate-Limit Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MinerU parse stage robust under the account-level submission rate limit (50 files/min) by adding a shared submission throttle (token bucket + global 429 pause), exposing `Retry-After`, persisting page-level parse state so completed pages are never re-uploaded, and routing pure rate-limit failures to a non-terminal retryable state.

**Architecture:** A new `MineruSubmissionThrottle` (token bucket pacing batch submissions below the rate limit, plus a process-wide pause gate tripped on HTTP 429) lives as a member of the single shared `MineruClient`. The transport layer is changed to return HTTP error responses (with headers) instead of raising, so 429/`Retry-After` are visible. A new `mineru_page_parse_state` table backs page-level resume inside `parse_pdf_by_pages`. A new `MineruRateLimitError` is raised when the limit persists past the pause budget; `process_document` treats it as `failed_retryable` without burning the terminal-failure count.

**Tech Stack:** Python 3, `unittest`, stdlib `urllib`, SQLite via raw `sqlite3` + `.sql` migration files, `threading` for the throttle.

**Spec:** `docs/superpowers/specs/2026-06-08-mineru-rate-limit-resilience-design.md`

---

## File Structure

- Create `src/newspaper_translator/mineru_throttle.py` — `MineruRateLimitError`, `parse_retry_after`, `MineruSubmissionThrottle` (token bucket + pause gate). No DB, no MinerU client deps.
- Create `src/newspaper_translator/mineru_page_state.py` — `PageParseState` dataclass + `MineruPageParseStateStore` (DB-backed resume state).
- Create `src/newspaper_translator/migrations/0014_mineru_page_parse_state.sql` — new table.
- Create `tests/test_mineru_throttle.py`, `tests/test_mineru_page_state.py`.
- Modify `src/newspaper_translator/mineru.py` — `_TransportResponse.headers`, transport captures `HTTPError`, throttle wiring into batch creation, resume in `parse_pdf_by_pages`, re-export `MineruRateLimitError`.
- Modify `src/newspaper_translator/config.py` — new `MineruSettings` fields.
- Modify `src/newspaper_translator/article_pipeline.py` — build the store and pass `document_key`/store into `parse_pdf_by_pages`.
- Modify `src/newspaper_translator/document_processing.py` — non-terminal path for `MineruRateLimitError`.
- Modify `tests/test_mineru.py`, `tests/test_config.py`, `tests/test_process_document.py`, `tests/test_article_pipeline.py` — cover the above.

---

## Task 1: Expose HTTP errors + headers in the transport layer

**Files:**
- Modify: `src/newspaper_translator/mineru.py`
- Test: `tests/test_mineru.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mineru.py` (inside `MineruClientTests`):

```python
def test_urllib_transport_returns_429_response_with_headers(self) -> None:
    self.assertIsNotNone(_UrllibTransport)
    from urllib.error import HTTPError

    def _raise_http_error(*_args, **_kwargs):
        raise HTTPError(
            url="https://mineru.net/api/v4/file-urls/batch",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "90"},
            fp=io.BytesIO(b"rate limited"),
        )

    transport = _UrllibTransport()
    with patch("newspaper_translator.mineru.request.urlopen", _raise_http_error):
        response = transport.request(
            method="POST",
            url="https://mineru.net/api/v4/file-urls/batch",
            headers={},
            body=b"{}",
            timeout=30,
        )

    self.assertEqual(response.status_code, 429)
    self.assertEqual(response.body, b"rate limited")
    self.assertEqual(response.headers.get("Retry-After"), "90")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mineru.py::MineruClientTests::test_urllib_transport_returns_429_response_with_headers -v`
Expected: FAIL — `_TransportResponse` has no `headers` / `HTTPError` propagates.

- [ ] **Step 3: Add `headers` to `_TransportResponse` and capture `HTTPError`**

In `src/newspaper_translator/mineru.py`, change the dataclass:

```python
@dataclass(frozen=True)
class _TransportResponse:
    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
```

Add `from dataclasses import dataclass, field` (update the existing import line). Change the import `from urllib.error import URLError` to `from urllib.error import HTTPError, URLError`.

Replace `_UrllibTransport.request` body:

```python
def request(
    self,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int | None = None,
) -> _TransportResponse:
    http_request = request.Request(url=url, data=body, headers=headers or {}, method=method)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with request.urlopen(http_request, timeout=timeout, context=ssl_context) as response:
            return _TransportResponse(
                status_code=response.getcode(),
                body=response.read(),
                headers={key: value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        return _TransportResponse(
            status_code=exc.code,
            body=exc.read(),
            headers={key: value for key, value in (exc.headers or {}).items()},
        )
```

- [ ] **Step 4: Update the existing `_FakeResponse` to accept headers**

In `tests/test_mineru.py`, change `_FakeResponse`:

```python
class _FakeResponse:
    def __init__(self, *, status_code: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_mineru.py -v`
Expected: PASS (all existing tests plus the new one).

- [ ] **Step 6: Commit**

```bash
git add src/newspaper_translator/mineru.py tests/test_mineru.py
git commit -m "feat: expose MinerU HTTP error responses and headers in transport"
```

---

## Task 2: Add rate-limit settings to `MineruSettings`

**Files:**
- Modify: `src/newspaper_translator/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (match the existing test style/imports in that file):

```python
def test_mineru_settings_reads_rate_limit_defaults_and_overrides(self) -> None:
    from newspaper_translator.config import MineruSettings

    defaults = MineruSettings.from_env({"MINERU_API_TOKEN": "t"})
    self.assertEqual(defaults.submit_rate_per_min, 45)
    self.assertEqual(defaults.rate_limit_pause_seconds, 120)
    self.assertEqual(defaults.rate_limit_max_pauses, 2)

    overridden = MineruSettings.from_env(
        {
            "MINERU_API_TOKEN": "t",
            "MINERU_SUBMIT_RATE_PER_MIN": "30",
            "MINERU_RATE_LIMIT_PAUSE_SECONDS": "180",
            "MINERU_RATE_LIMIT_MAX_PAUSES": "4",
        }
    )
    self.assertEqual(overridden.submit_rate_per_min, 30)
    self.assertEqual(overridden.rate_limit_pause_seconds, 180)
    self.assertEqual(overridden.rate_limit_max_pauses, 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -k rate_limit -v`
Expected: FAIL — `submit_rate_per_min` attribute missing.

- [ ] **Step 3: Add the fields**

In `src/newspaper_translator/config.py`, add to `MineruSettings` dataclass (after `poll_timeout_seconds`):

```python
    submit_rate_per_min: int = 45
    rate_limit_pause_seconds: int = 120
    rate_limit_max_pauses: int = 2
```

In `MineruSettings.from_env`, add to the `cls(...)` call (after `poll_timeout_seconds=...`):

```python
            submit_rate_per_min=_read_int_setting(
                env,
                "MINERU_SUBMIT_RATE_PER_MIN",
                default=45,
            ),
            rate_limit_pause_seconds=_read_int_setting(
                env,
                "MINERU_RATE_LIMIT_PAUSE_SECONDS",
                default=120,
            ),
            rate_limit_max_pauses=_read_int_setting(
                env,
                "MINERU_RATE_LIMIT_MAX_PAUSES",
                default=2,
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/config.py tests/test_config.py
git commit -m "feat: add MinerU rate-limit settings to MineruSettings"
```

---

## Task 3: Token bucket in `MineruSubmissionThrottle`

**Files:**
- Create: `src/newspaper_translator/mineru_throttle.py`
- Test: `tests/test_mineru_throttle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mineru_throttle.py`:

```python
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.mineru_throttle import MineruSubmissionThrottle


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class TokenBucketTests(unittest.TestCase):
    def test_acquire_within_capacity_does_not_sleep(self) -> None:
        clock = _FakeClock()
        throttle = MineruSubmissionThrottle(
            rate_per_min=45,
            pause_seconds=120,
            max_pauses=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        throttle.acquire(30)
        self.assertEqual(clock.sleeps, [])

    def test_acquire_beyond_capacity_sleeps_until_refilled(self) -> None:
        clock = _FakeClock()
        throttle = MineruSubmissionThrottle(
            rate_per_min=60,  # 1 token/second
            pause_seconds=120,
            max_pauses=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        throttle.acquire(60)  # drains the bucket, no sleep
        throttle.acquire(10)  # needs 10 more tokens -> ~10 seconds
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 10.0, places=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mineru_throttle.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the token bucket**

Create `src/newspaper_translator/mineru_throttle.py`:

```python
import threading
import time


class MineruRateLimitError(RuntimeError):
    """Raised when MinerU rate limiting persists past the configured pause budget."""


def parse_retry_after(headers: dict[str, str] | None, default_seconds: int) -> int:
    raw = None
    for key, value in (headers or {}).items():
        if key.lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return default_seconds
    try:
        parsed = int(str(raw).strip())
    except ValueError:
        return default_seconds
    return max(parsed, default_seconds)


class MineruSubmissionThrottle:
    def __init__(
        self,
        *,
        rate_per_min: int,
        pause_seconds: int,
        max_pauses: int,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._capacity = float(rate_per_min)
        self._refill_per_second = float(rate_per_min) / 60.0
        self._tokens = float(rate_per_min)
        self._pause_seconds = pause_seconds
        self._max_pauses = max_pauses
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_refill = monotonic()
        self._paused_until = 0.0
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = self._monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_second)
            self._last_refill = now

    def acquire(self, n_files: int) -> None:
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= n_files:
                    self._tokens -= n_files
                    return
                deficit = n_files - self._tokens
                wait_seconds = deficit / self._refill_per_second
            self._sleep(wait_seconds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mineru_throttle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/mineru_throttle.py tests/test_mineru_throttle.py
git commit -m "feat: add MinerU submission token-bucket throttle"
```

---

## Task 4: Pause gate + `submit()` retry loop + `MineruRateLimitError`

**Files:**
- Modify: `src/newspaper_translator/mineru_throttle.py`
- Test: `tests/test_mineru_throttle.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mineru_throttle.py`:

```python
from newspaper_translator.mineru_throttle import MineruRateLimitError, parse_retry_after


class _Resp:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class PauseGateTests(unittest.TestCase):
    def _throttle(self, clock: _FakeClock) -> MineruSubmissionThrottle:
        return MineruSubmissionThrottle(
            rate_per_min=600,  # large bucket so token waits don't interfere
            pause_seconds=120,
            max_pauses=2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    def test_submit_pauses_then_succeeds_after_429(self) -> None:
        clock = _FakeClock()
        throttle = self._throttle(clock)
        responses = [_Resp(429, {"Retry-After": "150"}), _Resp(200)]

        result = throttle.submit(n_files=1, perform=lambda: responses.pop(0))

        self.assertEqual(result.status_code, 200)
        self.assertIn(150.0, clock.sleeps)  # honored Retry-After (> default 120)

    def test_submit_raises_after_exceeding_max_pauses(self) -> None:
        clock = _FakeClock()
        throttle = self._throttle(clock)

        with self.assertRaises(MineruRateLimitError):
            throttle.submit(n_files=1, perform=lambda: _Resp(429))

    def test_parse_retry_after_uses_default_when_absent_and_max_otherwise(self) -> None:
        self.assertEqual(parse_retry_after({}, 120), 120)
        self.assertEqual(parse_retry_after({"Retry-After": "30"}, 120), 120)
        self.assertEqual(parse_retry_after({"retry-after": "200"}, 120), 200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mineru_throttle.py::PauseGateTests -v`
Expected: FAIL — `submit` not defined.

- [ ] **Step 3: Implement the pause gate and `submit`**

In `src/newspaper_translator/mineru_throttle.py`, add a pause-wait inside `acquire` and the `submit`/`note_rate_limited` methods. Replace `acquire` with:

```python
    def _wait_for_pause(self) -> None:
        while True:
            with self._lock:
                remaining = self._paused_until - self._monotonic()
            if remaining <= 0:
                return
            self._sleep(remaining)

    def acquire(self, n_files: int) -> None:
        self._wait_for_pause()
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= n_files:
                    self._tokens -= n_files
                    return
                deficit = n_files - self._tokens
                wait_seconds = deficit / self._refill_per_second
            self._sleep(wait_seconds)

    def note_rate_limited(self, retry_after_seconds: int) -> None:
        with self._lock:
            self._paused_until = self._monotonic() + retry_after_seconds

    def submit(self, *, n_files: int, perform):
        pauses = 0
        while True:
            self.acquire(n_files)
            response = perform()
            if getattr(response, "status_code", None) != 429:
                return response
            if pauses >= self._max_pauses:
                raise MineruRateLimitError(
                    "MinerU rate limit persisted after maximum pauses"
                )
            pauses += 1
            self.note_rate_limited(
                parse_retry_after(getattr(response, "headers", {}), self._pause_seconds)
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mineru_throttle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/mineru_throttle.py tests/test_mineru_throttle.py
git commit -m "feat: add MinerU 429 pause gate and submit retry budget"
```

---

## Task 5: Wire the throttle into `MineruClient` batch creation

**Files:**
- Modify: `src/newspaper_translator/mineru.py`
- Test: `tests/test_mineru.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mineru.py`. These use a fake clock so no real sleeping. Put the helper near the other helpers at module bottom:

```python
class _FakeThrottleClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
```

Add these tests inside `MineruClientTests`:

```python
def test_batch_create_pauses_on_429_then_succeeds(self) -> None:
    settings = MineruSettings(
        api_token="t", model_version="vlm", language="en", enable_ocr=False,
        enable_table=True, enable_formula=True, page_ranges="",
        poll_interval_seconds=0, poll_timeout_seconds=30,
    )
    clock = _FakeThrottleClock()
    success_body = json.dumps(
        {"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload/sample.pdf"]}}
    ).encode("utf-8")
    transport = _FakeTransport(
        responses=[
            _FakeResponse(status_code=429, body=b"", headers={"Retry-After": "120"}),
            _FakeResponse(status_code=200, body=success_body),
        ]
    )
    client = MineruClient(
        settings=settings, transport=transport,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )

    result = client._create_batch_upload(pathlib.Path("/tmp/sample.pdf"))

    self.assertEqual(result["batch_id"], "b1")
    self.assertGreaterEqual(clock.now, 120.0)  # paused before retrying

def test_batch_create_raises_rate_limit_error_when_persistent(self) -> None:
    from newspaper_translator.mineru import MineruRateLimitError

    settings = MineruSettings(
        api_token="t", model_version="vlm", language="en", enable_ocr=False,
        enable_table=True, enable_formula=True, page_ranges="",
        poll_interval_seconds=0, poll_timeout_seconds=30,
    )
    clock = _FakeThrottleClock()
    transport = _FakeTransport(
        responses=[_FakeResponse(status_code=429, body=b"") for _ in range(5)]
    )
    client = MineruClient(
        settings=settings, transport=transport,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )

    with self.assertRaises(MineruRateLimitError):
        client._create_batch_upload(pathlib.Path("/tmp/sample.pdf"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mineru.py -k "rate_limit or pauses_on_429" -v`
Expected: FAIL — `monotonic` kwarg unused for throttle, no throttle, no `MineruRateLimitError` export.

- [ ] **Step 3: Construct the throttle in `MineruClient.__init__` and extract a JSON validator**

In `src/newspaper_translator/mineru.py`:

Add the import near the top:

```python
from newspaper_translator.mineru_throttle import MineruRateLimitError, MineruSubmissionThrottle
```

In `MineruClient.__init__`, add a `throttle` parameter and construct a default:

```python
    def __init__(
        self,
        *,
        settings: MineruSettings,
        transport: _Transport | None = None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        max_request_attempts: int = 3,
        throttle: MineruSubmissionThrottle | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _UrllibTransport()
        self._sleep = sleep
        self._monotonic = monotonic
        self._max_request_attempts = max_request_attempts
        self._throttle = throttle or MineruSubmissionThrottle(
            rate_per_min=settings.submit_rate_per_min,
            pause_seconds=settings.rate_limit_pause_seconds,
            max_pauses=settings.rate_limit_max_pauses,
            sleep=sleep,
            monotonic=monotonic,
        )
```

Extract the response-validation half of `_request_json` into a reusable method, and have `_request_json` delegate to it:

```python
    def _validate_json_response(self, response: _TransportResponse) -> dict[str, object]:
        if response.status_code < 200 or response.status_code >= 300:
            raise MineruError(f"MinerU request failed with status {response.status_code}")
        payload = json.loads(response.body.decode("utf-8"))
        if payload.get("code") not in {0, 200}:
            raise MineruError(f"MinerU request failed with payload code {payload.get('code')}")
        return payload

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> dict[str, object]:
        response = self._request_with_retries(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout=self._settings.poll_timeout_seconds,
        )
        return self._validate_json_response(response)
```

- [ ] **Step 4: Route both batch-create paths through the throttle**

Replace `_create_batch_upload` (the single-PDF path) so its POST goes through `self._throttle.submit`:

```python
    def _create_batch_upload(self, pdf_path: Path) -> dict[str, str]:
        payload = {
            "enable_formula": self._settings.enable_formula,
            "enable_table": self._settings.enable_table,
            "language": self._settings.language,
            "model_version": self._settings.model_version,
            "files": [
                {
                    "name": pdf_path.name,
                    "is_ocr": self._settings.enable_ocr,
                    "page_ranges": self._settings.page_ranges,
                    "data_id": pdf_path.stem,
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        response = self._throttle.submit(
            n_files=1,
            perform=lambda: self._request_with_retries(
                method="POST",
                url="https://mineru.net/api/v4/file-urls/batch",
                headers=self._auth_headers(),
                body=body,
                timeout=self._settings.poll_timeout_seconds,
            ),
        )
        payload_json = self._validate_json_response(response)
        data = payload_json.get("data") or {}
        file_urls = data.get("file_urls") or []
        if not data.get("batch_id") or not file_urls:
            raise MineruError("MinerU batch upload response is missing batch_id or file_urls")
        return {
            "batch_id": str(data["batch_id"]),
            "upload_url": str(file_urls[0]),
        }
```

Replace `_create_batch_upload_for_files` (the page-batch path) the same way:

```python
    def _create_batch_upload_for_files(self, page_files) -> dict[str, object]:
        payload = {
            "enable_formula": self._settings.enable_formula,
            "enable_table": self._settings.enable_table,
            "language": self._settings.language,
            "model_version": self._settings.model_version,
            "files": [
                {
                    "name": page.path.name,
                    "is_ocr": self._settings.enable_ocr,
                    "page_ranges": "",
                    "data_id": page.path.stem,
                }
                for page in page_files
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        response = self._throttle.submit(
            n_files=len(page_files),
            perform=lambda: self._request_with_retries(
                method="POST",
                url="https://mineru.net/api/v4/file-urls/batch",
                headers=self._auth_headers(),
                body=body,
                timeout=self._settings.poll_timeout_seconds,
            ),
        )
        payload_json = self._validate_json_response(response)
        data = payload_json.get("data") or {}
        file_urls = data.get("file_urls") or []
        if not data.get("batch_id") or len(file_urls) != len(page_files):
            raise MineruError("MinerU batch upload response did not match submitted page files")
        return {
            "batch_id": str(data["batch_id"]),
            "file_urls": [str(file_url) for file_url in file_urls],
        }
```

Add `MineruRateLimitError` to the module's public surface — it is already importable via the Task 3 import line, so `from newspaper_translator.mineru import MineruRateLimitError` works. Confirm the import line from Step 3 is present.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_mineru.py -v`
Expected: PASS (existing batch tests still pass — non-429 responses pass straight through `submit`; with the default large bucket the existing `parse_pdf_by_pages` 31-page test still works because 30+1 tokens are available within capacity 45).

- [ ] **Step 6: Commit**

```bash
git add src/newspaper_translator/mineru.py tests/test_mineru.py
git commit -m "feat: throttle MinerU batch submissions and surface rate-limit errors"
```

---

## Task 6: Page-parse-state table + store

**Files:**
- Create: `src/newspaper_translator/migrations/0014_mineru_page_parse_state.sql`
- Create: `src/newspaper_translator/mineru_page_state.py`
- Test: `tests/test_mineru_page_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mineru_page_state.py`:

```python
import pathlib
import sys
import tempfile
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from newspaper_translator.database import run_pending_migrations
from newspaper_translator.mineru_page_state import MineruPageParseStateStore


class MineruPageParseStateStoreTests(unittest.TestCase):
    def test_mark_submitted_then_done_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_url = f"sqlite:///{pathlib.Path(temp_dir) / 'state.db'}"
            run_pending_migrations(database_url)
            store = MineruPageParseStateStore(database_url=database_url)

            store.mark_submitted(
                document_key="doc-1", page_number=1, batch_id="b1", file_name="page-0001.pdf"
            )
            store.mark_done(
                document_key="doc-1", page_number=1, batch_id="b1", file_name="page-0001.pdf",
                full_zip_url="https://z/1.zip", markdown_path="/out/page-0001/full.md",
            )
            store.mark_submitted(
                document_key="doc-1", page_number=2, batch_id="b1", file_name="page-0002.pdf"
            )

            states = store.load(document_key="doc-1")
            self.assertEqual(states[1].state, "done")
            self.assertEqual(states[1].markdown_path, "/out/page-0001/full.md")
            self.assertEqual(states[2].state, "submitted")
            self.assertEqual(states[2].batch_id, "b1")
            self.assertEqual(store.load(document_key="other"), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mineru_page_state.py -v`
Expected: FAIL — module/table missing.

- [ ] **Step 3: Create the migration**

Create `src/newspaper_translator/migrations/0014_mineru_page_parse_state.sql`:

```sql
CREATE TABLE mineru_page_parse_state (
    document_key TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    batch_id TEXT,
    file_name TEXT,
    state TEXT NOT NULL,
    full_zip_url TEXT,
    markdown_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_key, page_number)
);

CREATE INDEX idx_mineru_page_parse_state_document_key
    ON mineru_page_parse_state (document_key);
```

- [ ] **Step 4: Implement the store**

Create `src/newspaper_translator/mineru_page_state.py`:

```python
from dataclasses import dataclass
import sqlite3

from newspaper_translator.database import sqlite_path_from_database_url


@dataclass(frozen=True)
class PageParseState:
    page_number: int
    batch_id: str | None
    file_name: str | None
    state: str
    full_zip_url: str | None
    markdown_path: str | None


class MineruPageParseStateStore:
    def __init__(self, *, database_url: str) -> None:
        self._database_url = database_url

    def load(self, *, document_key: str) -> dict[int, PageParseState]:
        connection = sqlite3.connect(sqlite_path_from_database_url(self._database_url))
        try:
            rows = connection.execute(
                """
                SELECT page_number, batch_id, file_name, state, full_zip_url, markdown_path
                FROM mineru_page_parse_state
                WHERE document_key = ?
                """,
                (document_key,),
            ).fetchall()
        finally:
            connection.close()
        return {
            row[0]: PageParseState(
                page_number=row[0],
                batch_id=row[1],
                file_name=row[2],
                state=row[3],
                full_zip_url=row[4],
                markdown_path=row[5],
            )
            for row in rows
        }

    def mark_submitted(
        self, *, document_key: str, page_number: int, batch_id: str, file_name: str
    ) -> None:
        self._upsert(
            document_key=document_key,
            page_number=page_number,
            batch_id=batch_id,
            file_name=file_name,
            state="submitted",
            full_zip_url=None,
            markdown_path=None,
        )

    def mark_done(
        self,
        *,
        document_key: str,
        page_number: int,
        batch_id: str,
        file_name: str,
        full_zip_url: str,
        markdown_path: str,
    ) -> None:
        self._upsert(
            document_key=document_key,
            page_number=page_number,
            batch_id=batch_id,
            file_name=file_name,
            state="done",
            full_zip_url=full_zip_url,
            markdown_path=markdown_path,
        )

    def _upsert(
        self,
        *,
        document_key: str,
        page_number: int,
        batch_id: str | None,
        file_name: str | None,
        state: str,
        full_zip_url: str | None,
        markdown_path: str | None,
    ) -> None:
        connection = sqlite3.connect(sqlite_path_from_database_url(self._database_url))
        try:
            connection.execute(
                """
                INSERT INTO mineru_page_parse_state (
                    document_key, page_number, batch_id, file_name,
                    state, full_zip_url, markdown_path, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(document_key, page_number) DO UPDATE SET
                    batch_id = excluded.batch_id,
                    file_name = excluded.file_name,
                    state = excluded.state,
                    full_zip_url = excluded.full_zip_url,
                    markdown_path = excluded.markdown_path,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    document_key, page_number, batch_id, file_name,
                    state, full_zip_url, markdown_path,
                ),
            )
            connection.commit()
        finally:
            connection.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_mineru_page_state.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/newspaper_translator/migrations/0014_mineru_page_parse_state.sql src/newspaper_translator/mineru_page_state.py tests/test_mineru_page_state.py
git commit -m "feat: add MinerU page parse state table and store"
```

---

## Task 7: Page-level resume in `parse_pdf_by_pages`

**Files:**
- Modify: `src/newspaper_translator/mineru.py`
- Test: `tests/test_mineru.py`

**Behavior:** when a `page_state_store` and `document_key` are passed, pages already `done` are read from their stored markdown (no submit, no upload); pages `submitted` (uploaded earlier but result not yet saved) are re-polled by their `batch_id` and downloaded (no re-upload); only `pending`/unknown pages are submitted via the throttle. When no store is passed, behavior is unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mineru.py` inside `MineruClientTests`:

```python
def test_parse_pdf_by_pages_skips_done_pages_from_store(self) -> None:
    settings = MineruSettings(
        api_token="t", model_version="vlm", language="en", enable_ocr=False,
        enable_table=True, enable_formula=True, page_ranges="",
        poll_interval_seconds=0, poll_timeout_seconds=30,
    )
    page_files = [
        SimpleNamespace(page_number=n, path=pathlib.Path(f"/tmp/page-{n:04d}.pdf"))
        for n in range(1, 3)
    ]

    class _FakeStore:
        def __init__(self) -> None:
            self.done_marks: list[int] = []

        def load(self, *, document_key):
            return {
                1: SimpleNamespace(
                    page_number=1, batch_id="b0", file_name="page-0001.pdf",
                    state="done", full_zip_url="https://z/1.zip",
                    markdown_path=str(self._md_path),
                ),
            }

        def mark_submitted(self, **_kwargs):
            pass

        def mark_done(self, *, page_number, **_kwargs):
            self.done_marks.append(page_number)

    with tempfile.TemporaryDirectory() as temp_dir:
        md_path = pathlib.Path(temp_dir) / "page-0001" / "full.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("# Page 1\n\nDone earlier\n", encoding="utf-8")
        store = _FakeStore()
        store._md_path = md_path

        # Only page 2 should be submitted: one batch POST (1 file), one upload, one poll, one download.
        page2_create = json.dumps(
            {"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://upload/page-0002.pdf"]}}
        ).encode("utf-8")
        page2_poll = json.dumps(
            {"code": 0, "data": {"batch_id": "b1", "extract_result": [
                {"data_id": "page-0002", "file_name": "page-0002.pdf",
                 "state": "done", "full_zip_url": "https://z/2.zip"}]}}
        ).encode("utf-8")
        transport = _FakeTransport(responses=[
            _FakeResponse(status_code=200, body=page2_create),
            _FakeResponse(status_code=200, body=b""),
            _FakeResponse(status_code=200, body=page2_poll),
            _FakeResponse(status_code=200, body=_build_result_zip_bytes("# Page 2\n\nNew\n")),
        ])

        with patch("newspaper_translator.mineru.split_pdf_into_single_page_files", return_value=page_files):
            with patch.object(pathlib.Path, "read_bytes", return_value=b"%PDF page"):
                source_pdf = pathlib.Path(temp_dir) / "sample.pdf"
                source_pdf.write_bytes(b"%PDF sample")
                client = MineruClient(settings=settings, transport=transport)
                result = client.parse_pdf_by_pages(
                    pdf_path=source_pdf,
                    output_root=pathlib.Path(temp_dir) / "out",
                    document_key="doc-1",
                    page_state_store=store,
                )

    create_calls = [c for c in transport.calls
                    if c["method"] == "POST" and c["url"].endswith("/file-urls/batch")]
    self.assertEqual(len(create_calls), 1)  # page 1 not resubmitted
    submitted_files = json.loads(create_calls[0]["body"].decode("utf-8"))["files"]
    self.assertEqual([f["name"] for f in submitted_files], ["page-0002.pdf"])
    self.assertEqual({p.page_number for p in result.pages}, {1, 2})
    self.assertIn("Done earlier", dict((p.page_number, p.markdown_text) for p in result.pages)[1])
    self.assertEqual(store.done_marks, [2])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mineru.py::MineruClientTests::test_parse_pdf_by_pages_skips_done_pages_from_store -v`
Expected: FAIL — `parse_pdf_by_pages` has no `document_key`/`page_state_store` params.

- [ ] **Step 3: Rewrite `parse_pdf_by_pages` with resume**

Replace `parse_pdf_by_pages` in `src/newspaper_translator/mineru.py` with:

```python
    def parse_pdf_by_pages(
        self,
        *,
        pdf_path: Path,
        output_root: Path,
        max_batch_size: int = 30,
        document_key: str | None = None,
        page_state_store=None,
    ) -> MineruParsedDocument:
        pdf_path = Path(pdf_path)
        output_root = Path(output_root)
        page_output_dir = output_root / pdf_path.stem / "pages"
        page_files = split_pdf_into_single_page_files(
            pdf_path=pdf_path,
            output_dir=page_output_dir,
        )
        page_markdown_root = output_root / pdf_path.stem / "page-markdown"
        existing_states = (
            page_state_store.load(document_key=document_key)
            if page_state_store is not None and document_key is not None
            else {}
        )

        parsed_pages: list[MineruParsedPage] = []
        batch_ids: list[str] = []
        resume_pages = []  # (page, state) for state == "submitted"
        pending_pages = []  # need a fresh submit

        for page in page_files:
            state = existing_states.get(page.page_number)
            if state is not None and state.state == "done" and state.markdown_path:
                markdown_path = Path(state.markdown_path)
                parsed_pages.append(
                    MineruParsedPage(
                        page_number=page.page_number,
                        batch_id=state.batch_id or "",
                        file_id=page.path.stem,
                        file_name=state.file_name or page.path.name,
                        markdown_path=markdown_path,
                        markdown_text=markdown_path.read_text(encoding="utf-8"),
                    )
                )
                if state.batch_id:
                    batch_ids.append(state.batch_id)
            elif state is not None and state.state == "submitted" and state.batch_id:
                resume_pages.append((page, state))
            else:
                pending_pages.append(page)

        # Re-poll already-submitted batches without re-uploading.
        resume_by_batch: dict[str, list] = {}
        for page, state in resume_pages:
            resume_by_batch.setdefault(state.batch_id, []).append((page, state))
        for batch_id, items in resume_by_batch.items():
            batch_ids.append(batch_id)
            results = self._wait_for_extract_results(
                batch_id=batch_id,
                file_names={state.file_name or page.path.name for page, state in items},
            )
            for page, state in items:
                file_name = state.file_name or page.path.name
                self._finish_page(
                    page=page, batch_id=batch_id, result=results[file_name],
                    page_markdown_root=page_markdown_root, parsed_pages=parsed_pages,
                    document_key=document_key, page_state_store=page_state_store,
                )

        # Submit fresh pages in batches.
        for index in range(0, len(pending_pages), max_batch_size):
            batch_pages = pending_pages[index:index + max_batch_size]
            upload = self._create_batch_upload_for_files(batch_pages)
            batch_id = str(upload["batch_id"])
            batch_ids.append(batch_id)
            for page, upload_url in zip(batch_pages, upload["file_urls"]):
                self._upload_file(pdf_path=page.path, upload_url=upload_url)
                if page_state_store is not None and document_key is not None:
                    page_state_store.mark_submitted(
                        document_key=document_key, page_number=page.page_number,
                        batch_id=batch_id, file_name=page.path.name,
                    )
            results = self._wait_for_extract_results(
                batch_id=batch_id,
                file_names={page.path.name for page in batch_pages},
            )
            for page in batch_pages:
                result = results.get(page.path.name)
                if result is None:
                    raise MineruError(
                        f"MinerU page parse missing result for physical page {page.page_number}"
                    )
                self._finish_page(
                    page=page, batch_id=batch_id, result=result,
                    page_markdown_root=page_markdown_root, parsed_pages=parsed_pages,
                    document_key=document_key, page_state_store=page_state_store,
                )

        parsed_pages.sort(key=lambda page: page.page_number)
        merged_markdown_path, merged_markdown_text = self._write_merged_page_markdown(
            pages=parsed_pages,
            output_root=output_root,
            file_stem=pdf_path.stem,
        )
        return MineruParsedDocument(
            batch_id=",".join(dict.fromkeys(batch_ids)),
            file_id=pdf_path.stem,
            file_name=pdf_path.name,
            markdown_path=merged_markdown_path,
            markdown_text=merged_markdown_text,
            pages=tuple(parsed_pages),
        )

    def _finish_page(
        self,
        *,
        page,
        batch_id: str,
        result: dict,
        page_markdown_root: Path,
        parsed_pages: list,
        document_key: str | None,
        page_state_store,
    ) -> None:
        zip_bytes = self._download_bytes(result["full_zip_url"])
        try:
            markdown_path, markdown_text = self._extract_full_markdown(
                zip_bytes=zip_bytes,
                output_root=page_markdown_root,
                file_stem=f"page-{page.page_number:04d}",
            )
        except Exception as exc:
            raise MineruError(
                f"MinerU page parse failed for physical page {page.page_number}: {exc}"
            ) from exc
        parsed_pages.append(
            MineruParsedPage(
                page_number=page.page_number,
                batch_id=batch_id,
                file_id=result["file_id"],
                file_name=page.path.name,
                markdown_path=markdown_path,
                markdown_text=markdown_text,
            )
        )
        if page_state_store is not None and document_key is not None:
            page_state_store.mark_done(
                document_key=document_key, page_number=page.page_number,
                batch_id=batch_id, file_name=page.path.name,
                full_zip_url=result["full_zip_url"], markdown_path=str(markdown_path),
            )
```

Note: `page_markdown_root` replaces the previous inline `output_root / pdf_path.stem / "page-markdown"` argument passed to `_extract_full_markdown`; behavior is identical for the non-resume path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mineru.py -v`
Expected: PASS — the new resume test and the existing `test_parse_pdf_by_pages_uploads_single_page_files_in_batches_of_30` (which passes no store, so `existing_states` is empty and all pages are `pending`).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/mineru.py tests/test_mineru.py
git commit -m "feat: resume MinerU page parsing from persisted page state"
```

---

## Task 8: Wire the store into `persist_document_articles`

**Files:**
- Modify: `src/newspaper_translator/article_pipeline.py`
- Test: `tests/test_article_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_article_pipeline.py` (follow the file's existing fixture/import conventions; use a fake `mineru_client` that records kwargs):

```python
def test_persist_document_articles_passes_document_key_and_store(self) -> None:
    import tempfile, pathlib
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator import article_pipeline

    captured = {}

    class _FakeMineru:
        def parse_pdf_by_pages(self, *, pdf_path, output_root, document_key=None, page_state_store=None):
            captured["document_key"] = document_key
            captured["store_type"] = type(page_state_store).__name__
            return SimpleNamespace(
                batch_id="b1", file_id="f1", file_name="x.pdf",
                markdown_path=pathlib.Path(output_root) / "x.md",
                markdown_text="2026-01-02 news", pages=(),
            )

    with tempfile.TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{pathlib.Path(temp_dir) / 'db.sqlite'}"
        run_pending_migrations(database_url)
        # Insert a document row 'doc-1' with a raw_path using the helpers already
        # used elsewhere in this test module (mirror an existing test's document setup).
        _insert_minimal_document(database_url, document_key="doc-1", temp_dir=temp_dir)

        try:
            article_pipeline.persist_document_articles(
                database_url=database_url,
                document_key="doc-1",
                output_root=pathlib.Path(temp_dir) / "out",
                mineru_client=_FakeMineru(),
                continuation_matcher=None,
                parser_name="mineru",
                parser_version="vlm",
                continuation_matcher_name="",
                continuation_matcher_version="",
            )
        except Exception:
            pass  # later pipeline steps are out of scope; we only assert the parse call args

    self.assertEqual(captured["document_key"], "doc-1")
    self.assertEqual(captured["store_type"], "MineruPageParseStateStore")
```

If `tests/test_article_pipeline.py` has no `_insert_minimal_document`/document fixture helper, reuse the exact document-insertion approach already present in that file's other tests (search the file for how it seeds a `documents` row and a `raw_path`), and drop the helper call in favor of that inline setup.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_article_pipeline.py -k passes_document_key -v`
Expected: FAIL — `parse_pdf_by_pages` called without `document_key`/`page_state_store`.

- [ ] **Step 3: Pass the store and document key**

In `src/newspaper_translator/article_pipeline.py`, add the import at the top:

```python
from newspaper_translator.mineru_page_state import MineruPageParseStateStore
```

In `persist_document_articles`, change the parse call:

```python
    parsed_document = mineru_client.parse_pdf_by_pages(
        pdf_path=Path(document.raw_path),
        output_root=Path(output_root),
        document_key=document_key,
        page_state_store=MineruPageParseStateStore(database_url=database_url),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_article_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/article_pipeline.py tests/test_article_pipeline.py
git commit -m "feat: supply page-state store to MinerU page parsing"
```

---

## Task 9: Non-terminal `failed_retryable` path for rate-limit failures

**Files:**
- Modify: `src/newspaper_translator/document_processing.py`
- Test: `tests/test_process_document.py`

**Behavior:** when the parse step fails with `MineruRateLimitError`, the document is set to `failed_retryable` without incrementing `automatic_failure_count` (so a rate limit never pushes a document to `failed_terminal`), and the step is not retried in-process (the throttle's pause already absorbed the wait).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_process_document.py` (match its existing fixtures for a migrated temp DB and a created document run):

```python
def test_rate_limit_failure_is_retryable_and_not_counted(self) -> None:
    import tempfile, pathlib
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.mineru import MineruRateLimitError
    from newspaper_translator.document_processing import (
        process_document, get_document_processing_run,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{pathlib.Path(temp_dir) / 'db.sqlite'}"
        run_pending_migrations(database_url)
        document_key = "doc-rl"

        def _raise_rate_limit(*, document_key):
            raise MineruRateLimitError("limited")

        run = process_document(
            database_url=database_url,
            document_key=document_key,
            locked_by="w1",
            parse_persist_document=_raise_rate_limit,
            enrich_document=lambda *, document_key: None,
            step_retry_limit=2,
        )

        self.assertEqual(run.status, "failed_retryable")
        self.assertEqual(run.automatic_failure_count, 0)
        self.assertEqual(run.last_failure_step, "parse_persist")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_process_document.py -k rate_limit_failure_is_retryable -v`
Expected: FAIL — currently the rate-limit error is retried and counted, ending `failed_retryable` only after `automatic_failure_count` increments (or `failed_terminal`).

- [ ] **Step 3: Add a rate-limit-aware failure path**

In `src/newspaper_translator/document_processing.py`, add the import near the top:

```python
from newspaper_translator.mineru import MineruRateLimitError
```

Add a helper that marks a document `failed_retryable` without bumping the counter:

```python
def mark_document_rate_limited(
    *,
    database_url: str,
    document_key: str,
    failed_step: str,
    error_message: str,
    log_event=None,
) -> DocumentProcessingRun:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            connection.execute(
                """
                UPDATE document_processing_runs
                SET
                    status = 'failed_retryable',
                    current_step = ?,
                    last_failure_step = ?,
                    last_error_message = ?,
                    last_attempt_finished_at = CURRENT_TIMESTAMP,
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE document_key = ?
                """,
                (failed_step, failed_step, error_message, document_key),
            )
            connection.commit()
        finally:
            connection.close()

    _run_with_database_retries(callback)
    updated_run = _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url, document_key=document_key,
        ),
    )
    _log_event(
        log_event,
        event="document.rate_limited",
        details={
            "document_key": document_key,
            "failed_step": failed_step,
            "status": updated_run.status,
            "error_message": error_message,
        },
    )
    return updated_run
```

Make `_run_step_with_retry` stop retrying on a rate-limit error and report it distinctly. Change its loop body:

```python
    for attempt in range(step_retry_limit + 1):
        try:
            callback(document_key=document_key)
            return None
        except MineruRateLimitError as exc:
            return exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < step_retry_limit:
                _log_event(
                    log_event,
                    event="document.step.retry_scheduled",
                    details={
                        "document_key": document_key,
                        "step": step_name,
                        "attempt": attempt + 1,
                        "error_message": str(exc),
                    },
                )
    return last_error
```

In `process_document`, after the parse step's `_run_step_with_retry` call, branch on the error type before the existing `fail_document_processing_run` call:

```python
    if parse_error is not None:
        _log_event(
            log_event,
            event="document.step.finished",
            details={
                "document_key": document_key,
                "step": "parse_persist",
                "status": "failed",
            },
        )
        if isinstance(parse_error, MineruRateLimitError):
            return mark_document_rate_limited(
                database_url=database_url,
                document_key=document_key,
                failed_step="parse_persist",
                error_message=str(parse_error),
                log_event=log_event,
            )
        return fail_document_processing_run(
            database_url=database_url,
            document_key=document_key,
            failed_step="parse_persist",
            error_message=str(parse_error),
            log_event=log_event,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_document.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (no regressions across `test_mineru.py`, `test_config.py`, `test_article_pipeline.py`, `test_process_document.py`, and the rest).

- [ ] **Step 6: Commit**

```bash
git add src/newspaper_translator/document_processing.py tests/test_process_document.py
git commit -m "feat: route MinerU rate-limit failures to retryable, not terminal"
```

---

## Task 10: Document the new runtime knobs

**Files:**
- Modify: `docker-compose.yml`
- Modify: project docs that already list MinerU env vars (search for `MINERU_POLL_INTERVAL_SECONDS` to find them).

- [ ] **Step 1: Add env passthrough to compose**

In `docker-compose.yml`, under both the `worker` and `web` services' `environment:` blocks (next to the existing `MINERU_POLL_TIMEOUT_SECONDS` line), add:

```yaml
      MINERU_SUBMIT_RATE_PER_MIN: ${MINERU_SUBMIT_RATE_PER_MIN:-45}
      MINERU_RATE_LIMIT_PAUSE_SECONDS: ${MINERU_RATE_LIMIT_PAUSE_SECONDS:-120}
      MINERU_RATE_LIMIT_MAX_PAUSES: ${MINERU_RATE_LIMIT_MAX_PAUSES:-2}
```

- [ ] **Step 2: Document the knobs**

Find the doc that lists MinerU settings:

Run: `grep -rln "MINERU_POLL_TIMEOUT_SECONDS" docs/ README.md 2>/dev/null`

Add a short row/paragraph for each new variable to the file(s) found, describing: `MINERU_SUBMIT_RATE_PER_MIN` (default 45, token-bucket submission rate ceiling, keep below MinerU's 50 files/min), `MINERU_RATE_LIMIT_PAUSE_SECONDS` (default 120, pause length after a 429), `MINERU_RATE_LIMIT_MAX_PAUSES` (default 2, pauses tolerated before a document is re-queued as retryable).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml docs/ README.md
git commit -m "docs: document MinerU rate-limit runtime knobs"
```

---

## Self-Review Notes

- **Spec coverage:** Component 1 (throttle: token bucket + pause gate) → Tasks 3–5; Component 2 (transport headers/HTTPError) → Task 1; Component 3 (page-state table + resume) → Tasks 6–8; Component 4 (failed_retryable not terminal) → Task 9; config knobs → Tasks 2 & 10; testing strategy → tests embedded per task.
- **Type consistency:** `MineruSubmissionThrottle.submit(*, n_files, perform)`, `acquire(n_files)`, `note_rate_limited(retry_after_seconds)`; `MineruRateLimitError` defined in `mineru_throttle.py`, re-exported via `mineru.py`'s import and consumed in `document_processing.py`; `PageParseState(page_number, batch_id, file_name, state, full_zip_url, markdown_path)` matches store reads and the resume reads in `parse_pdf_by_pages`; `MineruPageParseStateStore.load/mark_submitted/mark_done` signatures match call sites in Tasks 7 & 8.
- **Assumption flagged in spec:** token unit = files declared in the `file-urls/batch` POST. If MinerU counts PUT uploads instead, only the `n_files=` argument source in Task 5 changes.
