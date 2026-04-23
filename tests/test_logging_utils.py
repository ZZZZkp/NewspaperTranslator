import json
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.logging_utils import format_log_event
except ImportError:
    format_log_event = None


class StructuredLoggingTests(unittest.TestCase):
    def test_formats_json_log_lines_with_shared_fields(self) -> None:
        self.assertIsNotNone(
            format_log_event,
            "format_log_event should be importable from newspaper_translator.logging_utils",
        )

        log_line = format_log_event(
            level="INFO",
            event="worker.startup",
            service="worker",
            details={"status": "ok", "database": "sqlite"},
            timestamp="2026-04-22T13:00:00Z",
        )

        payload = json.loads(log_line)

        self.assertEqual(payload["timestamp"], "2026-04-22T13:00:00Z")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["event"], "worker.startup")
        self.assertEqual(payload["service"], "worker")
        self.assertEqual(payload["details"]["status"], "ok")
        self.assertEqual(payload["details"]["database"], "sqlite")


if __name__ == "__main__":
    unittest.main()
