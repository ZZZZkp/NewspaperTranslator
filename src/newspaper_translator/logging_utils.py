import json
from datetime import UTC, datetime


def format_log_event(
    *,
    level: str,
    event: str,
    service: str,
    details: dict[str, object],
    timestamp: str | None = None,
) -> str:
    payload = {
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "service": service,
        "details": details,
    }
    return json.dumps(payload, sort_keys=True)
