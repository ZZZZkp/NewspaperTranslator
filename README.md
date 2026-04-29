# Newspaper Translator

This repository now has a complete runnable Phase 1 foundation, a working Phase 2 Gmail ingestion slice with durable import audit, incremental checkpointing, and failed-message retry support, plus a usable Phase 3 MinerU parsing path with explicit cross-page continuation matching and durable article persistence foundations.

## Current status

As of 2026-04-28, the project has:

- completed the Phase 1 local runtime baseline
- completed the first useful Phase 2 import path from Gmail into raw PDF storage
- added persisted import-run history and item-level audit records
- added read-only CLI and web query surfaces for import runs and run items
- added time-window incremental checkpointing for normal Gmail imports
- added automatic and manual retry flows for unresolved failed Gmail messages
- added MinerU-backed Phase 3 PDF parsing through the batch upload API
- added Markdown-to-article reconstruction for MinerU `full.md` outputs
- added a direct Markdown parsing CLI entry for local `full.md` debugging
- added explicit continuation-marker extraction for split newspaper articles
- added optional Gemini-backed matching and merge for explicit cross-page continuations
- added parse-run history persistence for repeated Phase 3 document parsing attempts
- added durable fragment, continuation-match, final-article, and article-lineage storage
- added publication-date persistence and fallback date resolution from parsed Markdown
- added enrichment-run, enrichment-output, and article-tag history storage foundations
- added current-version query rules for latest successful parsed articles and latest usable enrichment results
- validated Gmail Desktop OAuth locally
- validated Gmail API access through a local proxy or VPN
- validated direct PDF links such as `https://dl.dengtazk.xin/...pdf`
- validated QQ Mail landing pages such as `https://wx.mail.qq.com/ftn/download?...`, resolved through a JSON handoff
- validated real MinerU parsing end-to-end against a local Wall Street Journal sample PDF

Latest live Gmail import result on 2026-04-22:

- `fetched_message_count=25`
- `imported_attachment_count=4`
- `created_document_count=4`
- `skipped_document_count=0`

## Phase 3 parsing status

Phase 3 now uses the MinerU precision parsing API as its primary extraction path rather than a purely local PDF text-extraction path.

The current parsing flow is:

1. import raw newspaper PDFs from Gmail into local storage
2. submit the stored PDF files to MinerU through the precision parsing batch upload API
3. poll the batch result until the file reaches `done`
4. download the returned `full_zip_url`
5. extract `full.md` from the zip payload
6. extract article fragments from the MinerU Markdown result
7. if `GEMINI_TOKEN` is present, send only explicit continuation-bearing fragments to Gemini for matching
8. merge matched fragment pairs into final article-oriented outputs

Why this route:

- the official MinerU precision parsing API explicitly supports complex layouts, scanned inputs, tables, formulas, and multi-column pages
- the single-file API does not support direct file upload, so our local PDF workflow should use the documented batch upload flow
- the batch result returns `full.md`, which is a stronger Phase 3 parsing boundary than maintaining a separate local text-extraction path

Reference:

- [MinerU API docs](https://mineru.net/apiManage/docs)

Planned MinerU configuration:

- `MINERU_API_TOKEN`
- `MINERU_MODEL_VERSION`, default `vlm`
- `MINERU_LANGUAGE`, default `ch`
- `MINERU_ENABLE_OCR`, default `false`
- `MINERU_ENABLE_TABLE`, default `true`
- `MINERU_ENABLE_FORMULA`, default `true`
- `MINERU_POLL_INTERVAL_SECONDS`
- `MINERU_POLL_TIMEOUT_SECONDS`

Optional continuation-matching configuration:

- `GEMINI_TOKEN`
- `GEMINI_MODEL`, default `gemini-2.5-flash`
- `GEMINI_TIMEOUT_SECONDS`, default `120`

The repository now treats MinerU-backed Markdown parsing as the only supported Phase 3 article reconstruction path.

Run the current Phase 3 MinerU PDF parsing entry locally:

```bash
PYTHONPATH=src \
MINERU_API_TOKEN=your-mineru-token \
MINERU_MODEL_VERSION=vlm \
MINERU_LANGUAGE=ch \
./.venv/bin/python -m newspaper_translator.manage phase3-parse-pdf \
  --pdf-path ./sample-newspaper.pdf \
  --output-root ./tmp/phase3-output
```

If you already have a MinerU `full.md` file and want to reconstruct article structures directly:

```bash
PYTHONPATH=src \
./.venv/bin/python -m newspaper_translator.manage phase3-parse-md \
  --markdown-path ./tmp/phase3-output/sample-newspaper/full.md
```

Persist one imported document into the new Phase 3 article tables:

```bash
PYTHONPATH=src \
DATABASE_URL=sqlite:////tmp/newspaper-translator.db \
MINERU_API_TOKEN=your-mineru-token \
MINERU_MODEL_VERSION=vlm \
MINERU_LANGUAGE=ch \
./.venv/bin/python -m newspaper_translator.manage phase3-persist-document \
  --document-key message-id:attachment-id:content-hash \
  --output-root ./tmp/phase3-output
```

Inspect the latest visible article set and parse history for one imported document:

```bash
PYTHONPATH=src \
./.venv/bin/python -m newspaper_translator.manage phase3-latest-articles \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --document-key message-id:attachment-id:content-hash

PYTHONPATH=src \
./.venv/bin/python -m newspaper_translator.manage phase3-parse-runs \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --document-key message-id:attachment-id:content-hash
```

Inspect debug artifacts for one parse run:

```bash
PYTHONPATH=src \
./.venv/bin/python -m newspaper_translator.manage phase3-parse-run-fragments \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --parse-run-id your-parse-run-id

PYTHONPATH=src \
./.venv/bin/python -m newspaper_translator.manage phase3-parse-run-matches \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --parse-run-id your-parse-run-id

PYTHONPATH=src \
./.venv/bin/python -m newspaper_translator.manage phase3-parse-run-articles \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --parse-run-id your-parse-run-id
```

Current Phase 3 parser behavior:

- reconstructs article-like structures from MinerU Markdown headings and body text
- merges subtitle and `BY ...` heading patterns back into the same article
- drops obvious teaser and digest blocks that are not full articles
- detects explicit continuation markers such as `Please turn to page A7` and `Continued from PageOne`
- auto-enables Gemini continuation matching when `GEMINI_TOKEN` is present
- sends only continuation-bearing fragments to Gemini, then deterministically merges matched pairs and strips local marker text
- records fragment-level, match-level, and final-article lineage data for persisted parse runs
- returns merged article results through CLI JSON output while leaving unmatched fragments as standalone articles

Current Phase 3 parser limits:

- advertisement and statement filtering is intentionally deferred to later LLM-based post-processing
- only fragments with explicit continuation markers currently participate in LLM matching
- the parser does not yet infer cross-page relationships for fragments without explicit markers
- page numbers in Markdown-derived article JSON are parser-order indexes, not original newspaper page numbers

## Article Persistence Status

Phase 3 now has a durable article persistence layer on top of the existing MinerU parsing flow.

The current persistence model stores:

- one `parse_run` per parse attempt for one imported raw document
- raw `article_fragments` for each parse run
- `continuation_matches` with accepted, ignored, or invalid decisions
- immutable `final_articles` plus `final_article_fragments` lineage records
- one `article_enrichment_run` per enrichment attempt
- `article_enrichment_outputs` and ordered `article_tags` for usable enrichment results

Current version rules:

- the visible article set for a document comes from the latest successful `parse_run`
- a later failed parse run does not hide an older successful article set
- the visible enrichment layer for an article comes from the latest `partial` or `succeeded` enrichment run
- a later failed enrichment run does not hide an older usable enrichment result

## Local Python workflow

Create the virtual environment and run the test suite:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m unittest discover -s tests -v
```

Run the minimal web health endpoint locally:

```bash
PYTHONPATH=src \
APP_ENV=development \
DATABASE_URL=sqlite:////tmp/newspaper-translator.db \
STORAGE_ROOT=/tmp/newspaper-translator-data \
GMAIL_CONFIG_PATH=./config/gmail-config.json \
./.venv/bin/python -m newspaper_translator.web
```

Run the standalone migration and readiness commands:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage migrate --database-url sqlite:////tmp/newspaper-translator.db
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage check --service web \
  --app-env development \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --storage-root /tmp/newspaper-translator-data \
  --gmail-config-path ./config/gmail-config.json
```

Run a one-shot Gmail import:

1. Create a Google Cloud project, enable the Gmail API, and create a Desktop app OAuth client.
2. Put the downloaded OAuth client JSON at `secrets/google-oauth-client.json`.
3. Fill in `config/gmail-config.json`.
4. Apply the database schema:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage migrate \
  --database-url sqlite:////tmp/newspaper-translator.db
```

5. Run:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage gmail-import \
  --gmail-config ./config/gmail-config.json \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --storage-root /tmp/newspaper-translator-data
```

The first run will open the local OAuth flow in your browser and then write a reusable token file.

`GMAIL_CONFIG_PATH` is the unified runtime setting for Gmail integration. The OAuth client and token details should live behind that JSON config file rather than being duplicated in environment variables.

Inspect import audit state:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage gmail-import-runs \
  --database-url sqlite:////tmp/newspaper-translator.db
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage gmail-import-items \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --status failed
```

Manually retry unresolved failed Gmail messages:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage gmail-retry-failures \
  --gmail-config ./config/gmail-config.json \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --storage-root /tmp/newspaper-translator-data
```

For link-based newspaper emails:

- Set `enable_body_links` to `true`
- Use a query that matches the emails themselves, not only attachments
- Fill `allowed_link_domains` to restrict which PDF hosts are trusted
- `download_link_keywords` is used when a mail body links to a landing page that contains a PDF download button
- If Gmail must go through a local VPN or proxy, set `proxy_url`, for example `http://127.0.0.1:7897`
- For the current newspaper feed, the known-good domains are `dl.dengtazk.xin` and `wx.mail.qq.com`

## Docker workflow

Build and start the current Phase 1 runtime skeleton:

```bash
docker compose up --build
```

The `frontend` service is exposed on `${FRONTEND_PORT:-3000}` and the `web` service is exposed on `${WEB_PORT:-8000}`.
The `worker` service performs startup checks and emits structured JSON logs.
Both services also expose container healthchecks through `python -m newspaper_translator.manage check`.

To avoid host-port conflicts with other local Docker projects:

- `db` is only available on the internal Compose network by default and no longer binds host port `5432`
- set `FRONTEND_PORT` and `WEB_PORT` in `.env` when `3000` or `8000` are already in use

Example:

```bash
FRONTEND_PORT=3300
WEB_PORT=8100
docker compose up --build
```

## Current scope

Implemented today:

- shared environment loading
- SQLite migration baseline
- standalone `migrate` and `check` management commands
- minimal `web` and `worker` entrypoints
- health endpoint and startup checks
- compose healthchecks and explicit startup dependencies
- duplicate-safe raw PDF storage and document metadata persistence
- a Gmail import job that filters messages and imports matching PDF attachments
- Gmail Desktop OAuth via JSON config and reusable token storage
- Gmail API transport through a local proxy or VPN
- body-link import for direct PDF links in message bodies
- body-link import for QQ Mail landing pages that require `POST f=json` before downloading the PDF
- network-error tolerance for unrelated or broken body links so one bad URL does not fail the full import run
- persisted import-run and import-item audit records
- read-only import audit endpoints through `manage` and `web`
- time-window incremental checkpointing for Gmail imports
- automatic failed-message retry after normal imports
- manual failed-message retry through `gmail-retry-failures`
- retry/checkpoint summary fields on `import-runs`
- MinerU Markdown article-reconstruction tests
- Gemini-backed continuation matching for explicit cross-page article fragments
- parse-run persistence for Phase 3 document processing
- fragment, continuation-match, final-article, and lineage persistence tables
- publication-date extraction from filenames with Markdown fallback
- read-only CLI query surfaces for latest document articles and parse-run debug artifacts
- enrichment-run history, enrichment outputs, and ordered tag persistence foundations

Not implemented yet:

- LLM-based advertisement and statement filtering after Markdown parsing
- non-explicit cross-page continuation inference
- actual AI enrichment job execution for translation, summary, and tagging
- dashboard and richer browsing surfaces on top of the persisted article data
