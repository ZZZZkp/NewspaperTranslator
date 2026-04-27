import json
from dataclasses import dataclass
from pathlib import Path
import ssl
import time
from typing import Protocol
from urllib.error import URLError
from urllib import request
import zipfile

import certifi

from newspaper_translator.config import MineruSettings


class MineruError(RuntimeError):
    """Raised when the MinerU API returns an invalid or failed response."""


@dataclass(frozen=True)
class MineruParsedDocument:
    batch_id: str
    file_id: str
    file_name: str
    markdown_path: Path
    markdown_text: str


@dataclass(frozen=True)
class _TransportResponse:
    status_code: int
    body: bytes


class _Transport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> _TransportResponse: ...


class MineruClient:
    def __init__(
        self,
        *,
        settings: MineruSettings,
        transport: _Transport | None = None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        max_request_attempts: int = 3,
    ) -> None:
        self._settings = settings
        self._transport = transport or _UrllibTransport()
        self._sleep = sleep
        self._monotonic = monotonic
        self._max_request_attempts = max_request_attempts

    def parse_pdf(self, *, pdf_path: Path, output_root: Path) -> MineruParsedDocument:
        pdf_path = Path(pdf_path)
        output_root = Path(output_root)

        batch_upload = self._create_batch_upload(pdf_path)
        self._upload_file(pdf_path=pdf_path, upload_url=batch_upload["upload_url"])
        extract_result = self._wait_for_extract_result(
            batch_id=batch_upload["batch_id"],
            file_name=pdf_path.name,
        )
        zip_bytes = self._download_bytes(extract_result["full_zip_url"])
        markdown_path, markdown_text = self._extract_full_markdown(
            zip_bytes=zip_bytes,
            output_root=output_root,
            file_stem=pdf_path.stem,
        )

        return MineruParsedDocument(
            batch_id=batch_upload["batch_id"],
            file_id=extract_result["file_id"],
            file_name=pdf_path.name,
            markdown_path=markdown_path,
            markdown_text=markdown_text,
        )

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
        response = self._request_json(
            method="POST",
            url="https://mineru.net/api/v4/file-urls/batch",
            headers=self._auth_headers(),
            body=json.dumps(payload).encode("utf-8"),
        )
        data = response.get("data") or {}
        file_urls = data.get("file_urls") or []
        if not data.get("batch_id") or not file_urls:
            raise MineruError("MinerU batch upload response is missing batch_id or file_urls")

        file_url = str(file_urls[0])
        return {
            "batch_id": str(data["batch_id"]),
            "upload_url": file_url,
        }

    def _upload_file(self, *, pdf_path: Path, upload_url: str) -> None:
        response = self._request_with_retries(
            method="PUT",
            url=upload_url,
            headers={"Content-Type": ""},
            body=pdf_path.read_bytes(),
            timeout=self._settings.poll_timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise MineruError(f"MinerU upload failed with status {response.status_code}")

    def _wait_for_extract_result(self, *, batch_id: str, file_name: str) -> dict[str, str]:
        deadline = self._monotonic() + self._settings.poll_timeout_seconds
        url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"

        while True:
            response = self._request_json(
                method="GET",
                url=url,
                headers=self._auth_headers(),
            )
            data = response.get("data") or {}
            extract_results = data.get("extract_result") or []
            for result in extract_results:
                result_file_name = str(result.get("file_name") or result.get("name") or "")
                if result_file_name != file_name:
                    continue
                if result.get("state") == "done" and result.get("full_zip_url"):
                    return {
                        "file_id": str(result.get("file_id") or result.get("data_id") or file_name),
                        "full_zip_url": str(result["full_zip_url"]),
                    }

            if self._monotonic() >= deadline:
                raise MineruError(f"Timed out waiting for MinerU batch {batch_id}")
            self._sleep(self._settings.poll_interval_seconds)

    def _download_bytes(self, url: str) -> bytes:
        response = self._request_with_retries(
            method="GET",
            url=url,
            headers={},
            body=None,
            timeout=self._settings.poll_timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise MineruError(f"MinerU download failed with status {response.status_code}")
        return response.body

    def _extract_full_markdown(
        self,
        *,
        zip_bytes: bytes,
        output_root: Path,
        file_stem: str,
    ) -> tuple[Path, str]:
        output_root.mkdir(parents=True, exist_ok=True)
        extraction_dir = output_root / file_stem
        extraction_dir.mkdir(parents=True, exist_ok=True)

        zip_path = extraction_dir / "result.zip"
        zip_path.write_bytes(zip_bytes)

        with zipfile.ZipFile(zip_path) as zip_file:
            zip_file.extractall(extraction_dir)
            markdown_name = next(
                (name for name in zip_file.namelist() if name.endswith("full.md")),
                None,
            )

        if not markdown_name:
            raise MineruError("MinerU result zip does not contain full.md")

        markdown_path = extraction_dir / markdown_name
        markdown_text = markdown_path.read_text(encoding="utf-8")
        return markdown_path, markdown_text

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
        if response.status_code < 200 or response.status_code >= 300:
            raise MineruError(f"MinerU request failed with status {response.status_code}")

        payload = json.loads(response.body.decode("utf-8"))
        if payload.get("code") not in {0, 200}:
            raise MineruError(f"MinerU request failed with payload code {payload.get('code')}")
        return payload

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.api_token}",
            "Content-Type": "application/json",
        }

    def _request_with_retries(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> _TransportResponse:
        last_error: Exception | None = None
        for attempt in range(1, self._max_request_attempts + 1):
            try:
                return self._transport.request(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    timeout=timeout,
                )
            except URLError as exc:
                last_error = exc
                if attempt >= self._max_request_attempts:
                    raise
                self._sleep(1)

        if last_error is not None:
            raise last_error
        raise MineruError("MinerU request failed without a response")


class _UrllibTransport:
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
        with request.urlopen(http_request, timeout=timeout, context=ssl_context) as response:
            return _TransportResponse(status_code=response.getcode(), body=response.read())
