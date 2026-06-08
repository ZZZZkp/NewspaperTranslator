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
