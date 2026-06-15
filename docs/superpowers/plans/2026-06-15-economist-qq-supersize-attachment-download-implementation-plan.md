# Economist QQ Super-Large-Attachment Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-download the weekly Economist e-edition (English original only) from the new QQ "超大附件" email sender, label its source as `经济学人`, and feed it into the existing Economist parse path.

**Architecture:** The existing Gmail body-link downloader already resolves `wx.mail.qq.com/ftn/download` landing pages via a JSON POST and downloads the result. We extend the resolver to also return the real filename from the QQ JSON (`body.name`), use that name so the `【译】` translation is filtered *before* its ~12 MB download, and map the Economist e-edition filename to the source label `经济学人` at import time. Plus one config line to allow the new sender.

**Tech Stack:** Python, `requests`, sqlite3, `unittest` / `pytest`.

---

## File Structure

- `src/newspaper_translator/gmail.py` — add `ResolvedDownload` dataclass; resolver + `_build_attachment_from_url` thread the real filename and skip the translation before download; `HttpLinkDownloader.resolve_download_url` captures `body.name`.
- `src/newspaper_translator/ingestion.py` — `_extract_source_name_from_filename` returns `经济学人` for the Economist e-edition filename.
- `config/gmail-config.json` — add the new sender.
- `tests/test_gmail.py` — new tests for named resolution + translated pre-download skip; existing QQ test stays green.
- `tests/test_ingestion_source_name.py` (or existing ingestion test module) — source-label assertions.

**Note on verification:** Run tests with the project venv. Use:
`./.venv/bin/python -m pytest <path> -v`

---

## Task 1: Resolver returns real filename; English original imported with correct name

**Files:**
- Modify: `src/newspaper_translator/gmail.py` (`_resolve_download_url` ~969-977, `_build_attachment_from_url` ~897-945, `HttpLinkDownloader.resolve_download_url` ~1098-1114; add `ResolvedDownload` near top dataclasses)
- Test: `tests/test_gmail.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gmail.py`. First extend the import block (lines 27-31) to also import `ResolvedDownload`:

```python
    from newspaper_translator.gmail import (
        build_gmail_service,
        import_from_gmail,
        load_gmail_integration_config,
        ResolvedDownload,
    )
```

And add `ResolvedDownload = None` to the matching `except ImportError:` block.

Add a new downloader double and test (place the double near `_FakeQqMailLandingPageDownloader`, ~line 1649):

```python
class _FakeNamedQqMailLandingPageDownloader:
    def __init__(self, *, filename: str) -> None:
        self._filename = filename
        self.resolved_urls: list[str] = []
        self.downloaded_urls: list[str] = []

    def resolve_download_url(self, url: str):
        self.resolved_urls.append(url)
        if url == "https://wx.mail.qq.com/ftn/download?func=3&key=landing":
            return ResolvedDownload(
                url="https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123",
                filename=self._filename,
            )
        return None

    def download_binary(self, url: str) -> bytes:
        self.downloaded_urls.append(url)
        if url == "https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123":
            return b"%PDF-1.7 te-edition"
        raise AssertionError(f"Unexpected binary download URL: {url}")

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for QQ landing page URL: {url}")
```

```python
    def test_qq_super_large_attachment_uses_resolved_filename_as_original_filename(self) -> None:
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(ResolvedDownload)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["wx.mail.qq.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            downloader = _FakeNamedQqMailLandingPageDownloader(
                filename="TE-2026-06-13-PDF_WEB.pdf"
            )
            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeQqMailLandingPageService(),
                downloader=downloader,
            )

            connection = sqlite3.connect(database_path)
            try:
                stored_row = connection.execute(
                    "SELECT original_filename FROM documents"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(summary.created_document_count, 1)
        self.assertEqual(
            downloader.downloaded_urls,
            ["https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123"],
        )
        self.assertEqual(stored_row[0], "TE-2026-06-13-PDF_WEB.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_gmail.py::GmailIntegrationTests::test_qq_super_large_attachment_uses_resolved_filename_as_original_filename -v`
Expected: FAIL — `ImportError`/`AttributeError` for `ResolvedDownload`, or stored filename is `download.pdf`.

- [ ] **Step 3: Add the `ResolvedDownload` dataclass**

In `src/newspaper_translator/gmail.py`, near the other `@dataclass(frozen=True)` definitions (after `GmailRetrySummary`, ~line 77), add:

```python
@dataclass(frozen=True)
class ResolvedDownload:
    url: str
    filename: str | None = None
```

(`from dataclasses import dataclass` is already imported.)

- [ ] **Step 4: Normalize the resolver helper return type**

Replace `_resolve_download_url` (~969-977):

```python
def _resolve_download_url(
    *,
    url: str,
    downloader,
) -> ResolvedDownload | None:
    resolver = getattr(downloader, "resolve_download_url", None)
    if not callable(resolver):
        return None
    result = resolver(url)
    if result is None:
        return None
    if isinstance(result, ResolvedDownload):
        return result
    return ResolvedDownload(url=str(result))
```

(The `str` branch keeps any resolver that still returns a bare URL string working, so existing tests pass unchanged.)

- [ ] **Step 5: Use the real filename in `_build_attachment_from_url`**

Replace the resolver branch in `_build_attachment_from_url` (~910-918):

```python
    resolved_download = _resolve_download_url(
        url=url,
        downloader=downloader,
    )
    if resolved_download is not None:
        filename = resolved_download.filename or _filename_from_url(resolved_download.url)
        return _build_body_link_attachment(
            source_url=url,
            filename=filename,
            content_bytes=downloader.download_binary(resolved_download.url),
        )
```

- [ ] **Step 6: Capture `body.name` in the production resolver**

Replace `HttpLinkDownloader.resolve_download_url` (~1098-1114):

```python
    def resolve_download_url(self, url: str) -> "ResolvedDownload | None":
        if not _is_qq_mail_landing_page(url):
            return None

        import requests

        response = requests.post(url, data={"f": "json"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        body = payload.get("body", {})
        if not isinstance(body, dict):
            return None

        candidate_url = body.get("url") or body.get("download_url") or payload.get("download_url")
        if not candidate_url:
            return None
        return ResolvedDownload(url=str(candidate_url), filename=body.get("name") or None)
```

- [ ] **Step 7: Run the new test and the existing QQ test**

Run: `./.venv/bin/python -m pytest tests/test_gmail.py::GmailIntegrationTests::test_qq_super_large_attachment_uses_resolved_filename_as_original_filename tests/test_gmail.py::GmailIntegrationTests::test_imports_pdf_documents_from_qq_mail_landing_pages_via_json_resolution -v`
Expected: both PASS. (The existing test's fake returns a bare `str`, normalized by Step 4, so it still stores `download.pdf`.)

- [ ] **Step 8: Commit**

```bash
git add src/newspaper_translator/gmail.py tests/test_gmail.py
git commit -m "feat: thread QQ super-large-attachment filename through download resolver"
```

---

## Task 2: Skip the translated copy before downloading

**Files:**
- Modify: `src/newspaper_translator/gmail.py` (`_build_attachment_from_url` resolver branch)
- Test: `tests/test_gmail.py`

- [ ] **Step 1: Write the failing test**

Add a downloader double whose `download_binary` must never be called, plus the test:

```python
class _FakeTranslatedQqMailLandingPageDownloader:
    def __init__(self, *, filename: str) -> None:
        self._filename = filename
        self.downloaded_urls: list[str] = []

    def resolve_download_url(self, url: str):
        if url == "https://wx.mail.qq.com/ftn/download?func=3&key=landing":
            return ResolvedDownload(
                url="https://wx.mail.qq.com/ftn/download?func=4&key=resolved&code=123",
                filename=self._filename,
            )
        return None

    def download_binary(self, url: str) -> bytes:
        raise AssertionError(f"Translated copy must not be downloaded: {url}")

    def fetch_html(self, url: str) -> str:
        raise AssertionError(f"Should not fetch HTML for QQ landing page URL: {url}")
```

```python
    def test_qq_super_large_translated_attachment_is_skipped_before_download(self) -> None:
        self.assertIsNotNone(import_from_gmail)
        self.assertIsNotNone(list_import_run_items)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            config_path = temp_path / "gmail-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "oauth_client_secrets_path": "./secrets/google-client.json",
                        "oauth_token_path": "./secrets/gmail-token.json",
                        "allowed_senders": ["briefing@example.com"],
                        "query": "newer_than:7d",
                        "label_ids": ["INBOX"],
                        "max_results": 10,
                        "include_spam_trash": False,
                        "enable_body_links": True,
                        "allowed_link_domains": ["wx.mail.qq.com"],
                        "download_link_keywords": ["download", "pdf"],
                    }
                )
            )

            storage_root = temp_path / "storage"
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            summary = import_from_gmail(
                config_path=config_path,
                storage_root=storage_root,
                database_url=database_url,
                service=_FakeQqMailLandingPageService(),
                downloader=_FakeTranslatedQqMailLandingPageDownloader(
                    filename="【译】TE-2026-06-13-PDF_WEB.pdf"
                ),
            )

            skipped_items = list_import_run_items(
                database_url=database_url,
                run_id=summary.run_id,
                status="skipped",
            )

        self.assertEqual(summary.created_document_count, 0)
        filtered = [i for i in skipped_items if i.detail_code == "body_link_filename_filtered"]
        self.assertEqual(len(filtered), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_gmail.py::GmailIntegrationTests::test_qq_super_large_translated_attachment_is_skipped_before_download -v`
Expected: FAIL with `AssertionError: Translated copy must not be downloaded: ...` (current code downloads before filtering).

- [ ] **Step 3: Add the pre-download translated skip**

In `_build_attachment_from_url`, update the resolver branch (from Task 1) to skip the download when the resolved name is a translation. `_is_translated_pdf_filename` is already imported at the top of `gmail.py`:

```python
    resolved_download = _resolve_download_url(
        url=url,
        downloader=downloader,
    )
    if resolved_download is not None:
        filename = resolved_download.filename or _filename_from_url(resolved_download.url)
        if resolved_download.filename and _is_translated_pdf_filename(filename):
            return _build_body_link_attachment(
                source_url=url,
                filename=filename,
                content_bytes=b"",
            )
        return _build_body_link_attachment(
            source_url=url,
            filename=filename,
            content_bytes=downloader.download_binary(resolved_download.url),
        )
```

The returned attachment carries the real `【译】…` name and empty bytes; the caller `_extract_pdf_links_from_message_body` filters it by name (gmail.py ~566) and records the `body_link_filename_filtered` audit item, never reading the bytes.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_gmail.py::GmailIntegrationTests::test_qq_super_large_translated_attachment_is_skipped_before_download -v`
Expected: PASS.

- [ ] **Step 5: Run the full gmail suite for regressions**

Run: `./.venv/bin/python -m pytest tests/test_gmail.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/newspaper_translator/gmail.py tests/test_gmail.py
git commit -m "feat: skip QQ super-large translated copy before downloading"
```

---

## Task 3: Label the Economist e-edition source as 经济学人

**Files:**
- Modify: `src/newspaper_translator/ingestion.py` (imports + `_extract_source_name_from_filename` ~237-258)
- Test: `tests/test_ingestion_source_name.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingestion_source_name.py`:

```python
import unittest

from newspaper_translator.ingestion import _extract_source_name_from_filename


class ExtractSourceNameTests(unittest.TestCase):
    def test_economist_eedition_filename_maps_to_economist_label(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("TE-2026-06-13-PDF_WEB.pdf"),
            "经济学人",
        )

    def test_translated_economist_eedition_also_maps_to_economist_label(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("【译】TE-2026-06-13-PDF_WEB.pdf"),
            "经济学人",
        )

    def test_ordinary_dated_filename_keeps_prefix(self) -> None:
        self.assertEqual(
            _extract_source_name_from_filename("金融时报-5-6.pdf"),
            "金融时报",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_ingestion_source_name.py -v`
Expected: the two Economist tests FAIL (returns `TE-2026-06-13-PDF_WEB` / `【译】TE-2026-06-13-PDF_WEB`); the `金融时报` test PASSES.

- [ ] **Step 3: Add the import and helper, and short-circuit the extractor**

In `src/newspaper_translator/ingestion.py`, add `import unicodedata` to the import block (after `import sqlite3`, line 6).

Add a module-level pattern and helper above `_extract_source_name_from_filename` (~line 237):

```python
_ECONOMIST_EDITION_FILENAME_RE = re.compile(
    r"^TE[-_]\d{4}[-_]\d{1,2}[-_]\d{1,2}[-_]PDF[-_]WEB$",
    re.IGNORECASE,
)


def _is_economist_edition_filename(filename: str) -> bool:
    stem = unicodedata.normalize("NFKC", Path(filename).name)
    stem = Path(stem).stem
    stem = stem.removeprefix("【译】")
    return bool(_ECONOMIST_EDITION_FILENAME_RE.match(stem))
```

Then add the short-circuit as the first lines of `_extract_source_name_from_filename`:

```python
def _extract_source_name_from_filename(filename: str) -> str:
    if _is_economist_edition_filename(filename):
        return "经济学人"
    stem = Path(filename).name
    stem = Path(stem).stem
    ...
```

(Leave the rest of `_extract_source_name_from_filename` unchanged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_ingestion_source_name.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/ingestion.py tests/test_ingestion_source_name.py
git commit -m "feat: label economist e-edition documents with 经济学人 source name"
```

---

## Task 4: Allow the new QQ sender in config

**Files:**
- Modify: `config/gmail-config.json`

- [ ] **Step 1: Add the sender**

In `config/gmail-config.json`, add `"903817461@qq.com"` to `allowed_senders`:

```json
  "allowed_senders": [
    "13802809612@163.com",
    "dengtawaikan@dengtazk.xin",
    "903817461@qq.com"
  ],
```

(`allowed_link_domains` already contains `wx.mail.qq.com` — no change.)

- [ ] **Step 2: Verify the config still parses**

Run: `./.venv/bin/python -c "from pathlib import Path; from newspaper_translator.gmail import load_gmail_integration_config; c = load_gmail_integration_config(Path('config/gmail-config.json')); print('903817461@qq.com' in c.allowed_senders)"`
Expected: prints `True`.

- [ ] **Step 3: Commit**

```bash
git add config/gmail-config.json
git commit -m "config: allow economist e-edition QQ sender 903817461@qq.com"
```

---

## Final Verification

- [ ] **Run the full affected test suites**

Run: `./.venv/bin/python -m pytest tests/test_gmail.py tests/test_ingestion_source_name.py -v`
Expected: all PASS.

- [ ] **Confirm publication date still resolves (no code change, sanity check)**

Run: `./.venv/bin/python -c "from newspaper_translator.article_pipeline import resolve_publication_date; print(resolve_publication_date(original_filename='TE-2026-06-13-PDF_WEB.pdf', markdown_text=''))"`
Expected: prints `2026-06-13`.

---

## Notes / Out of Scope

- No change to the Economist parser, persistence, or enrichment — the imported `TE-*-PDF_WEB.pdf` flows through the existing route unchanged.
- No support for normal (non-super-large) QQ attachments or the `mail.qq.com` web UI; the verified func=3 JSON resolution is sufficient.
- After implementation, update the `economist-eedition-path` memory note to mention the new download path/sender.
