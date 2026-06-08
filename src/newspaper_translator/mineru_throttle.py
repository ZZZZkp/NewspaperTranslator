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
        if rate_per_min <= 0:
            raise ValueError(f"rate_per_min must be positive, got {rate_per_min}")
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
                if self._tokens >= n_files or self._tokens >= self._capacity:
                    self._tokens -= n_files
                    return
                # When n_files exceeds capacity, wait only until the bucket is full.
                target = min(float(n_files), self._capacity)
                deficit = target - self._tokens
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
