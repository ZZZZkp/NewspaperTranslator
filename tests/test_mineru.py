import io
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
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

            headers = {}

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

    def test_parse_pdf_by_pages_uploads_single_page_files_in_batches_of_30(self) -> None:
        from newspaper_translator.mineru import MineruParsedPage

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
        page_files = [
            SimpleNamespace(page_number=page_number, path=pathlib.Path(f"/tmp/page-{page_number:04d}.pdf"))
            for page_number in range(1, 32)
        ]
        transport = _FakeTransport(
            responses=_build_page_batch_responses(page_count=31)
        )

        with patch("newspaper_translator.mineru.split_pdf_into_single_page_files", return_value=page_files):
            with patch.object(pathlib.Path, "read_bytes", return_value=b"%PDF-1.4 page"):
                with tempfile.TemporaryDirectory() as temp_dir:
                    source_pdf = pathlib.Path(temp_dir) / "sample.pdf"
                    source_pdf.write_bytes(b"%PDF-1.4 sample")
                    client = MineruClient(settings=settings, transport=transport)

                    result = client.parse_pdf_by_pages(
                        pdf_path=source_pdf,
                        output_root=pathlib.Path(temp_dir) / "mineru-output",
                    )

                    merged_markdown_path = result.markdown_path
                    self.assertTrue(merged_markdown_path.exists())
                    merged_text = merged_markdown_path.read_text(encoding="utf-8")
                    self.assertIn("<!-- PDF_PAGE_NUMBER: 1 -->", merged_text)
                    self.assertIn("<!-- PDF_PAGE_NUMBER: 31 -->", merged_text)

        self.assertEqual(len(result.pages), 31)
        self.assertIsInstance(result.pages[0], MineruParsedPage)
        self.assertEqual(result.pages[0].page_number, 1)
        self.assertEqual(result.pages[-1].page_number, 31)
        create_calls = [
            call for call in transport.calls
            if call["method"] == "POST" and call["url"].endswith("/api/v4/file-urls/batch")
        ]
        self.assertEqual(len(create_calls), 2)
        first_payload = json.loads(create_calls[0]["body"].decode("utf-8"))
        second_payload = json.loads(create_calls[1]["body"].decode("utf-8"))
        self.assertEqual(len(first_payload["files"]), 30)
        self.assertEqual(len(second_payload["files"]), 1)

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
    def __init__(self, *, status_code: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}


class _FakeThrottleClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _build_result_zip_bytes(markdown_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("sample/full.md", markdown_text)
    return buffer.getvalue()


def _build_page_batch_responses(*, page_count: int) -> list["_FakeResponse"]:
    responses: list[_FakeResponse] = []
    for batch_index, start_page in enumerate(range(1, page_count + 1, 30), start=1):
        pages = list(range(start_page, min(start_page + 30, page_count + 1)))
        responses.append(
            _FakeResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "batch_id": f"batch-{batch_index}",
                            "file_urls": [
                                f"https://upload.example.com/page-{page_number:04d}.pdf"
                                for page_number in pages
                            ],
                        },
                    }
                ).encode("utf-8"),
            )
        )
        responses.extend(_FakeResponse(status_code=200, body=b"") for _ in pages)
        responses.append(
            _FakeResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "batch_id": f"batch-{batch_index}",
                            "extract_result": [
                                {
                                    "data_id": f"page-{page_number:04d}",
                                    "file_name": f"page-{page_number:04d}.pdf",
                                    "state": "done",
                                    "full_zip_url": f"https://download.example.com/page-{page_number:04d}.zip",
                                }
                                for page_number in pages
                            ],
                        },
                    }
                ).encode("utf-8"),
            )
        )
        responses.extend(
            _FakeResponse(
                status_code=200,
                body=_build_result_zip_bytes(f"# Page {page_number}\n\nBody {page_number}\n"),
            )
            for page_number in pages
        )
    return responses


if __name__ == "__main__":
    unittest.main()
