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


def main() -> None:
    print(build_startup_log_line(dict(os.environ)), flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
