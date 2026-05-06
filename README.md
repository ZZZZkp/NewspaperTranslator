# Newspaper Translator

This repository now has a runnable local newspaper-processing stack: Gmail PDF ingestion, durable import audit and retry tracking, MinerU-backed article reconstruction, Gemini-backed continuation matching and article enrichment, scheduled background processing, and a standalone reading/operator frontend.

## Current status

As of 2026-05-06, the project has:

- completed the Phase 1 local runtime baseline
- completed the current Phase 2 import path from Gmail into raw PDF storage
- added persisted import-run history and item-level audit records
- added read-only CLI and web query surfaces for import runs and run items
- added time-window incremental checkpointing for normal Gmail imports
- added automatic and manual retry flows for unresolved failed Gmail messages
- added body-link imports for direct PDF links, QQ Mail landing pages, and the current `dengtazk.xin:8282` email-download flow
- added stable short body-link attachment identifiers so long signed URLs no longer leak into raw storage paths
- added conservative translated-PDF filename filtering for known translated variants, including `【译】`-prefixed PDFs from attachments and body links
- added automatic `document_processing_runs` enqueueing for imported Gmail documents so the continuous worker picks them up without a legacy queue handoff
- removed the legacy `processing_tasks` table and backfilled missing document-processing rows during migration `0011`
- added MinerU-backed Phase 3 PDF parsing through the batch upload API
- added Markdown-to-article reconstruction for MinerU `full.md` outputs
- added a direct Markdown parsing CLI entry for local `full.md` debugging
- added explicit continuation-marker extraction for split newspaper articles
- added optional Gemini-backed matching and merge for explicit cross-page continuations
- added parse-run history persistence for repeated Phase 3 document parsing attempts
- added durable fragment, continuation-match, final-article, article-image, and article-lineage storage
- added publication-date persistence and fallback date resolution from parsed Markdown
- added enrichment-run, enrichment-output, and article-tag history storage
- added executable Gemini-backed article translation, Chinese summary, and tagging
- added current-version query rules for latest successful parsed articles and latest usable enrichment results
- added a scheduler-driven document-processing control plane with stale-run recovery and manual retry
- split article enrichment into article-stage processing with durable `article_key` identity, input-hash reuse, stale-run recovery, and manual retry
- added CLI and web/API entry points for document-processing and article-processing status/retry operations
- added dashboard APIs for overview counts, article cards, article detail, filters, and focus-tag feeds
- added a standalone `frontend/` dashboard and operator workbench with document-processing and article-processing views
- split worker orchestration so Gmail import keeps its 2-hour cadence while document/article processing polls queued work continuously
- added a manual Gmail import API and operator-workbench button for fetching latest mail attachments into the queue
- extended the frontend Nginx API proxy timeout so slower Gmail imports do not fail with a proxy `504`
- added Gemini direct API mode plus OpenAI-compatible gateway mode
- validated Gmail Desktop OAuth locally
- validated Gmail API access through a local proxy or VPN
- validated direct PDF links such as `https://dl.dengtazk.xin/...pdf`
- validated QQ Mail landing pages such as `https://wx.mail.qq.com/ftn/download?...`, resolved through a JSON handoff
- validated `https://www.dengtazk.xin:8282/api/public/email-download...` body links for direct and preview-page PDF flows
- validated real MinerU parsing end-to-end against a local Wall Street Journal sample PDF
- validated Docker startup with writable Gmail token storage under the mounted `secrets` directory

Latest recorded live Gmail import result from the completed 2026-05-06 import/enqueue verification:

- Docker `web` and `worker` were healthy with proxy-backed network access
- `fetched_message_count=6`
- `imported_attachment_count=2`
- `created_document_count=0`
- `skipped_document_count=2`
- `status=succeeded`
- no imported `documents.original_filename` started with `【译】`
- no imported document was missing a `document_processing_runs` row

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
- `GEMINI_API_COMPAT_MODE`, default `standard`
- `GOOGLE_GEMINI_BASE_URL`, used when `GEMINI_API_COMPAT_MODE=openai_compatible`
- `GEMINI_API_KEY`, used when `GEMINI_API_COMPAT_MODE=openai_compatible`
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
- persists fragment page numbers and final-article source page numbers where available
- returns merged article results through CLI JSON output while leaving unmatched fragments as standalone articles

Current Phase 3 parser limits:

- advertisement and statement filtering is intentionally deferred to later LLM-based post-processing
- only fragments with explicit continuation markers currently participate in LLM matching
- the parser does not yet infer cross-page relationships for fragments without explicit markers
- page-number fidelity depends on the MinerU output; parser-derived article JSON can still fall back to parser-order indexes when original page labels are unavailable

## Article Persistence Status

Phase 3 now has a durable article persistence layer on top of the existing MinerU parsing flow.

The current persistence model stores:

- one `parse_run` per parse attempt for one imported raw document
- raw `article_fragments` for each parse run
- `continuation_matches` with accepted, ignored, or invalid decisions
- immutable `final_articles` plus `final_article_fragments` lineage records
- one `article_enrichment_run` per enrichment attempt
- `article_enrichment_outputs` and ordered `article_tags` for usable enrichment results
- durable `article_processing_runs` for article-stage translation, summary, tagging, retry, and stale-run recovery

Current version rules:

- the visible article set for a document comes from the latest successful `parse_run`
- a later failed parse run does not hide an older successful article set
- the visible enrichment layer for an article comes from the latest `partial` or `succeeded` enrichment run
- a later failed enrichment run does not hide an older usable enrichment result
- `article_key` tracks the same logical article across repeated parses of the same document lineage when title/opening text and source pages are similar
- unchanged article inputs can reuse a previous successful enrichment result by input hash, while manual retry forces a fresh attempt

## Dashboard And Operator Workbench

The standalone frontend in `frontend/` is now the primary local product surface. It is served by the Compose `frontend` service and calls the backend through Nginx.

Current frontend capabilities:

- reading dashboard with overview cards, source/tag/date filters, focus-tag sections, and article cards
- article detail view with Chinese, English, and comparison modes
- document-processing workbench list and document detail views
- article-processing workbench list and article-processing detail views
- manual Gmail import from the processing workbench through `立即拉取邮件`
- manual retry actions for document and article processing
- navigation between reading detail, owning document detail, and article-processing detail

Current API surfaces include:

- `GET /api/overview`
- `GET /api/articles`
- `GET /api/articles/<article_id>`
- `GET /api/filters`
- `GET /api/focus-tags/articles`
- `GET /api/document-processing`
- `GET /api/document-processing/<document_key>`
- `POST /api/document-processing/<document_key>/retry`
- `POST /api/gmail/import`
- `GET /api/article-processing`
- `GET /api/article-processing/<article_key>`
- `POST /api/article-processing/<article_key>/retry`

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
- For the current newspaper feed, the known-good domains are `dl.dengtazk.xin`, `www.dengtazk.xin`, and `wx.mail.qq.com`
- Body-link attachments use short stable `link:body-...` identifiers internally while preserving the original URL in import audit records
- Known translated PDF filename variants are skipped conservatively and recorded as skipped import items rather than failed imports; this includes literal and percent-encoded `【译】` body-link filenames

## Docker workflow

Build and start the current local stack:

```bash
docker compose up --build
```

The `frontend` service is exposed on `${FRONTEND_PORT:-3000}` and the `web` service is exposed on `${WEB_PORT:-8000}`.
The `worker` service performs startup checks, stale-run recovery, 2-hour Gmail import catch-up, and continuous document/article processing. It emits structured JSON logs.
The frontend proxies `/api/` requests to `web` with an extended read timeout so manual Gmail imports can finish even when upstream mail links are slow.
Both services also expose container healthchecks through `python -m newspaper_translator.manage check`.

`./config` is mounted read-only into `web` and `worker`. `./secrets` is mounted writable because Gmail OAuth credentials may refresh and write the reusable token file back to `secrets/gmail-token.json`.

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

Implemented so far:

- shared environment loading
- SQLite migration baseline
- standalone `migrate` and `check` management commands
- runnable `web` and `worker` entrypoints
- health endpoint and startup checks
- compose healthchecks and explicit startup dependencies
- duplicate-safe raw PDF storage and document metadata persistence
- a Gmail import job that filters messages and imports matching PDF attachments
- Gmail Desktop OAuth via JSON config and reusable token storage
- Gmail API transport through a local proxy or VPN
- body-link import for direct PDF links in message bodies
- body-link import for QQ Mail landing pages that require `POST f=json` before downloading the PDF
- body-link import for the current `dengtazk.xin:8282` email-download flow
- stable body-link identity and short storage-facing names for long signed URLs
- conservative translated-PDF filename filtering, including `【译】` prefixes and percent-encoded body-link basenames
- import-time enqueueing into `document_processing_runs` with retry recovery for documents whose enqueue failed after metadata commit
- migration `0011_drop_processing_tasks` that backfills missing document-processing rows and removes the legacy `processing_tasks` table
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
- enrichment-run history, enrichment outputs, and ordered tag persistence
- executable Gemini-backed article translation, summary, and tagging
- OpenAI-compatible gateway mode for Gemini-style article and continuation clients
- scheduler-driven document-processing and article-processing control planes
- stale-run recovery, manual retry, and CLI/web/API inspection for both document and article processing
- dashboard query surfaces for overview, article cards, article details, filters, and focus tags
- standalone frontend dashboard, article reader, document-processing workbench, and article-processing workbench

Not implemented yet:

- LLM-based advertisement and statement filtering after Markdown parsing
- non-explicit cross-page continuation inference
- browser-driven manual QA and broader visual polish for the newest article-processing workbench
- deeper frontend regression coverage beyond the current static-shell and API tests
