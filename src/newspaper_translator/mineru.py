import json
from dataclasses import dataclass, field
from pathlib import Path
import ssl
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib import request
import zipfile

import certifi

from newspaper_translator.config import MineruSettings
from newspaper_translator.pdf import split_pdf_into_single_page_files


class MineruError(RuntimeError):
    """Raised when the MinerU API returns an invalid or failed response."""


@dataclass(frozen=True)
class MineruParsedPage:
    page_number: int
    batch_id: str
    file_id: str
    file_name: str
    markdown_path: Path
    markdown_text: str


@dataclass(frozen=True)
class MineruParsedDocument:
    batch_id: str
    file_id: str
    file_name: str
    markdown_path: Path
    markdown_text: str
    pages: tuple["MineruParsedPage", ...] = ()


@dataclass(frozen=True)
class _TransportResponse:
    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


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

    def parse_pdf_by_pages(
        self,
        *,
        pdf_path: Path,
        output_root: Path,
        max_batch_size: int = 30,
    ) -> MineruParsedDocument:
        pdf_path = Path(pdf_path)
        output_root = Path(output_root)
        page_output_dir = output_root / pdf_path.stem / "pages"
        page_files = split_pdf_into_single_page_files(
            pdf_path=pdf_path,
            output_dir=page_output_dir,
        )
        parsed_pages: list[MineruParsedPage] = []
        batch_ids: list[str] = []

        for index in range(0, len(page_files), max_batch_size):
            batch_pages = page_files[index:index + max_batch_size]
            upload = self._create_batch_upload_for_files(batch_pages)
            batch_id = str(upload["batch_id"])
            batch_ids.append(batch_id)
            for page, upload_url in zip(batch_pages, upload["file_urls"]):
                self._upload_file(pdf_path=page.path, upload_url=upload_url)
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
                zip_bytes = self._download_bytes(result["full_zip_url"])
                try:
                    markdown_path, markdown_text = self._extract_full_markdown(
                        zip_bytes=zip_bytes,
                        output_root=output_root / pdf_path.stem / "page-markdown",
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

        parsed_pages.sort(key=lambda page: page.page_number)
        merged_markdown_path, merged_markdown_text = self._write_merged_page_markdown(
            pages=parsed_pages,
            output_root=output_root,
            file_stem=pdf_path.stem,
        )
        return MineruParsedDocument(
            batch_id=",".join(batch_ids),
            file_id=pdf_path.stem,
            file_name=pdf_path.name,
            markdown_path=merged_markdown_path,
            markdown_text=merged_markdown_text,
            pages=tuple(parsed_pages),
        )

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
        response = self._request_json(
            method="POST",
            url="https://mineru.net/api/v4/file-urls/batch",
            headers=self._auth_headers(),
            body=json.dumps(payload).encode("utf-8"),
        )
        data = response.get("data") or {}
        file_urls = data.get("file_urls") or []
        if not data.get("batch_id") or len(file_urls) != len(page_files):
            raise MineruError("MinerU batch upload response did not match submitted page files")
        return {
            "batch_id": str(data["batch_id"]),
            "file_urls": [str(file_url) for file_url in file_urls],
        }

    def _wait_for_extract_results(
        self,
        *,
        batch_id: str,
        file_names: set[str],
    ) -> dict[str, dict[str, str]]:
        deadline = self._monotonic() + self._settings.poll_timeout_seconds
        url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        while True:
            response = self._request_json(method="GET", url=url, headers=self._auth_headers())
            data = response.get("data") or {}
            extract_results = data.get("extract_result") or []
            done_results: dict[str, dict[str, str]] = {}
            for result in extract_results:
                file_name = str(result.get("file_name") or result.get("name") or "")
                if file_name not in file_names:
                    continue
                if result.get("state") == "done" and result.get("full_zip_url"):
                    done_results[file_name] = {
                        "file_id": str(result.get("file_id") or result.get("data_id") or file_name),
                        "full_zip_url": str(result["full_zip_url"]),
                    }
            if set(done_results) == file_names:
                return done_results
            if self._monotonic() >= deadline:
                unfinished = sorted(file_names - set(done_results))
                raise MineruError(
                    f"Timed out waiting for MinerU batch {batch_id}; unfinished files: {', '.join(unfinished)}"
                )
            self._sleep(self._settings.poll_interval_seconds)

    def _write_merged_page_markdown(
        self,
        *,
        pages: list[MineruParsedPage],
        output_root: Path,
        file_stem: str,
    ) -> tuple[Path, str]:
        merged_dir = output_root / file_stem
        merged_dir.mkdir(parents=True, exist_ok=True)
        merged_path = merged_dir / "full-pages.md"
        parts = []
        for page in pages:
            parts.append(
                f"<!-- PDF_PAGE_NUMBER: {page.page_number} -->\n{page.markdown_text.strip()}\n"
            )
        merged_text = "\n".join(parts)
        merged_path.write_text(merged_text, encoding="utf-8")
        return merged_path, merged_text

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
