from datetime import datetime, timedelta
import os
import time

from newspaper_translator.logging_utils import format_log_event
from newspaper_translator.runtime import build_runtime_report


def build_startup_report(env: dict[str, str]) -> dict[str, object]:
    return build_runtime_report(env=env, service="worker")


def build_startup_log_line(
    env: dict[str, str],
    *,
    timestamp: str | None = None,
) -> str:
    report = build_startup_report(env)
    return format_log_event(
        level="INFO" if report["status"] == "ok" else "ERROR",
        event="worker.startup",
        service="worker",
        details=report,
        timestamp=timestamp,
    )


def should_run_catch_up_tick(
    *,
    last_scheduler_run_started_at: str | None,
    now: str,
    interval_seconds: int,
) -> bool:
    if not last_scheduler_run_started_at:
        return True
    last_started_at = _parse_timestamp(last_scheduler_run_started_at)
    now_dt = _parse_timestamp(now)
    return now_dt - last_started_at >= timedelta(seconds=interval_seconds)


def main() -> None:
    print(build_startup_log_line(dict(os.environ)), flush=True)
    while True:
        time.sleep(60)


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    main()
