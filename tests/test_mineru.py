import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
import zipfile


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.config import MineruSettings
    from newspaper_translator.mineru import MineruClient, MineruParsedDocument, _UrllibTransport
except ImportError:
    MineruSettings = None
    MineruClient = None
    MineruParsedDocument = None
    _UrllibTransport = None


class MineruClientTests(unittest.TestCase):
    def test_uploads_local_pdf_polls_batch_and_extracts_full_md(self) -> None:
        self.assertIsNotNone(MineruSettings, "MineruSettings should be importable from newspaper_translator.config")
        self.assertIsNotNone(MineruClient, "MineruClient should be importable from newspaper_translator.mineru")
        self.assertIsNotNone(MineruParsedDocument, "MineruParsedDocument should be importable from newspaper_translator.mineru")

        settings = MineruSettings(
            api_token="mineru-token",
            model_version="vlm",
            language="en",
            enable_ocr=True,
            enable_table=True,
            enable_formula=False,
            page_ranges="1-2",
            poll_interval_seconds=0,
            poll_timeout_seconds=30,
        )

        result_zip_bytes = _build_result_zip_bytes("# Headline\n\nParagraph one.\n")
        transport = _FakeTransport(
            responses=[
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "batch_id": "batch-1",
                                "file_urls": [
                                    "https://upload.example.com/sample.pdf"
                                ],
                            },
                        }
                    ).encode("utf-8"),
                ),
                _FakeResponse(status_code=200, body=b""),
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "batch_id": "batch-1",
                                "extract_result": [
                                    {
                                        "data_id": "sample",
                                        "file_name": "sample.pdf",
                                        "state": "done",
                                        "full_zip_url": "https://download.example.com/result.zip",
                                    }
                                ],
                            },
                        }
                    ).encode("utf-8"),
                ),
                _FakeResponse(status_code=200, body=result_zip_bytes),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            output_root = pathlib.Path(temp_dir) / "mineru-output"

            client = MineruClient(settings=settings, transport=transport)
            result = client.parse_pdf(pdf_path=pdf_path, output_root=output_root)

            self.assertEqual(result.batch_id, "batch-1")
            self.assertEqual(result.file_id, "sample")
            self.assertEqual(result.file_name, "sample.pdf")
            self.assertEqual(result.markdown_text, "# Headline\n\nParagraph one.\n")
            self.assertTrue(result.markdown_path.exists())
            self.assertEqual(result.markdown_path.read_text(encoding="utf-8"), "# Headline\n\nParagraph one.\n")

        create_batch_call = transport.calls[0]
        self.assertEqual(create_batch_call["method"], "POST")
        self.assertEqual(create_batch_call["url"], "https://mineru.net/api/v4/file-urls/batch")
        self.assertEqual(create_batch_call["headers"]["Authorization"], "Bearer mineru-token")

        request_payload = json.loads(create_batch_call["body"].decode("utf-8"))
        self.assertEqual(request_payload["enable_formula"], False)
        self.assertEqual(request_payload["enable_table"], True)
        self.assertEqual(request_payload["language"], "en")
        self.assertEqual(request_payload["model_version"], "vlm")
        self.assertEqual(request_payload["files"][0]["name"], "sample.pdf")
        self.assertEqual(request_payload["files"][0]["is_ocr"], True)
        self.assertEqual(request_payload["files"][0]["page_ranges"], "1-2")

        upload_call = transport.calls[1]
        self.assertEqual(upload_call["method"], "PUT")
        self.assertEqual(upload_call["headers"]["Content-Type"], "")

    def test_urllib_transport_uses_certifi_ca_bundle(self) -> None:
        self.assertIsNotNone(_UrllibTransport, "_UrllibTransport should be importable from newspaper_translator.mineru")

        transport = _UrllibTransport()

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def getcode(self):
                return 200

            def read(self):
                return b"ok"

        with patch("newspaper_translator.mineru.request.urlopen", return_value=_Response()) as urlopen:
            response = transport.request(method="GET", url="https://mineru.net/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"ok")
        self.assertIn("context", urlopen.call_args.kwargs)
        self.assertIsNotNone(urlopen.call_args.kwargs["context"])

    def test_retries_transient_poll_transport_errors(self) -> None:
        settings = MineruSettings(
            api_token="mineru-token",
            model_version="vlm",
            language="en",
            enable_ocr=False,
            enable_table=True,
            enable_formula=True,
            page_ranges="",
            poll_interval_seconds=0,
            poll_timeout_seconds=30,
        )

        transport = _RetryingFakeTransport(
            events=[
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "batch_id": "batch-1",
                                "file_urls": ["https://upload.example.com/sample.pdf"],
                            },
                        }
                    ).encode("utf-8"),
                ),
                _FakeResponse(status_code=200, body=b""),
                URLError("temporary eof"),
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "batch_id": "batch-1",
                                "extract_result": [
                                    {
                                        "data_id": "sample",
                                        "file_name": "sample.pdf",
                                        "state": "done",
                                        "full_zip_url": "https://download.example.com/result.zip",
                                    }
                                ],
                            },
                        }
                    ).encode("utf-8"),
                ),
                _FakeResponse(status_code=200, body=_build_result_zip_bytes("# Headline\n\nBody\n")),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            output_root = pathlib.Path(temp_dir) / "mineru-output"

            client = MineruClient(settings=settings, transport=transport)
            result = client.parse_pdf(pdf_path=pdf_path, output_root=output_root)

        self.assertEqual(result.file_id, "sample")
        self.assertEqual(result.markdown_text, "# Headline\n\nBody\n")

    def test_retries_transient_upload_transport_errors(self) -> None:
        settings = MineruSettings(
            api_token="mineru-token",
            model_version="vlm",
            language="en",
            enable_ocr=False,
            enable_table=True,
            enable_formula=True,
            page_ranges="",
            poll_interval_seconds=0,
            poll_timeout_seconds=30,
        )

        transport = _RetryingFakeTransport(
            events=[
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "batch_id": "batch-1",
                                "file_urls": ["https://upload.example.com/sample.pdf"],
                            },
                        }
                    ).encode("utf-8"),
                ),
                URLError("temporary eof"),
                _FakeResponse(status_code=200, body=b""),
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "batch_id": "batch-1",
                                "extract_result": [
                                    {
                                        "data_id": "sample",
                                        "file_name": "sample.pdf",
                                        "state": "done",
                                        "full_zip_url": "https://download.example.com/result.zip",
                                    }
                                ],
                            },
                        }
                    ).encode("utf-8"),
                ),
                _FakeResponse(status_code=200, body=_build_result_zip_bytes("# Headline\n\nBody\n")),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = pathlib.Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            output_root = pathlib.Path(temp_dir) / "mineru-output"

            client = MineruClient(settings=settings, transport=transport)
            result = client.parse_pdf(pdf_path=pdf_path, output_root=output_root)

        self.assertEqual(result.file_id, "sample")
        self.assertEqual(result.markdown_text, "# Headline\n\nBody\n")


class _FakeTransport:
    def __init__(self, *, responses: list["_FakeResponse"]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> "_FakeResponse":
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": body,
                "timeout": timeout,
            }
        )
        return self._responses.pop(0)


class _RetryingFakeTransport:
    def __init__(self, *, events: list[object]) -> None:
        self._events = list(events)

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> "_FakeResponse":
        event = self._events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


class _FakeResponse:
    def __init__(self, *, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


def _build_result_zip_bytes(markdown_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("sample/full.md", markdown_text)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
