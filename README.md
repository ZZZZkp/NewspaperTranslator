# Newspaper Translator

This repository now has a complete runnable Phase 1 foundation plus a working Phase 2 Gmail ingestion slice.

## Current status

As of 2026-04-22, the project has:

- completed the Phase 1 local runtime baseline
- completed the first useful Phase 2 import path from Gmail into raw PDF storage
- validated Gmail Desktop OAuth locally
- validated Gmail API access through a local proxy or VPN
- validated direct PDF links such as `https://dl.dengtazk.xin/...pdf`
- validated QQ Mail landing pages such as `https://wx.mail.qq.com/ftn/download?...`, resolved through a JSON handoff

Latest live Gmail import result on 2026-04-22:

- `fetched_message_count=25`
- `imported_attachment_count=4`
- `created_document_count=4`
- `skipped_document_count=0`

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
GMAIL_CLIENT_ID=local-client-id \
GMAIL_CLIENT_SECRET=local-client-secret \
GMAIL_REFRESH_TOKEN=local-refresh-token \
./.venv/bin/python -m newspaper_translator.web
```

Run the standalone migration and readiness commands:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage migrate --database-url sqlite:////tmp/newspaper-translator.db
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage check --service web \
  --app-env development \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --storage-root /tmp/newspaper-translator-data \
  --gmail-client-id local-client-id \
  --gmail-client-secret local-client-secret \
  --gmail-refresh-token local-refresh-token
```

Run a one-shot Gmail import:

1. Create a Google Cloud project, enable the Gmail API, and create a Desktop app OAuth client.
2. Put the downloaded OAuth client JSON at `secrets/google-oauth-client.json`.
3. Fill in [config/gmail-config.json](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/config/gmail-config.json:1).
4. Apply the database schema:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage migrate \
  --database-url sqlite:////tmp/newspaper-translator.db
```

5. Run:

```bash
PYTHONPATH=src ./.venv/bin/python -m newspaper_translator.manage gmail-import \
  --gmail-config /Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/config/gmail-config.json \
  --database-url sqlite:////tmp/newspaper-translator.db \
  --storage-root /tmp/newspaper-translator-data
```

The first run will open the local OAuth flow in your browser and then write a reusable token file.

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

The `web` service exposes `GET /healthz` on port `8000`.
The `worker` service performs startup checks and emits structured JSON logs.
Both services also expose container healthchecks through `python -m newspaper_translator.manage check`.

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
- real PDF inspection tests against sample newspapers

Not implemented yet:

- persisted import-run history and failure audit trail
- article reconstruction from newspaper pages
- OCR
- enrichment and dashboard features
