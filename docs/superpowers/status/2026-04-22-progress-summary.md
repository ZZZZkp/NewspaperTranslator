# Newspaper Translator Progress Summary

Date: 2026-04-22

## Current Stage

The project has moved from planning into executable TDD-based implementation.

Phase 1 foundation work is complete, and the repository now has a working first Phase 2 ingestion slice.

The codebase now contains:

- A project-local Python virtual environment workflow
- A minimal Python application structure under `src/newspaper_translator`
- A growing test suite under `tests`
- A minimal runnable local runtime with `web` and `worker` entrypoints
- A SQLite migration baseline and shared startup checks
- Standalone runtime management commands for migration and readiness checks
- A structured JSON logging helper for runtime services
- A duplicate-safe raw PDF import path backed by SQLite metadata persistence
- A Gmail API adapter with Desktop OAuth configuration, proxy support, and a one-shot import command
- A first real PDF adapter validated against sample newspaper files

## Implemented Foundations

### Configuration

Implemented in:

- [config.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/config.py)
- [test_config.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_config.py)

Current behavior:

- Loads required application settings from environment variables
- Fails fast when required Gmail credentials are missing

### Document Identity

Implemented in:

- [documents.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/documents.py)
- [test_documents.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_documents.py)

Current behavior:

- Builds a stable document key from message id, attachment id, and content hash
- Produces the same logical key for repeated imports of the same attachment

### Task State Machine

Implemented in:

- [tasks.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/tasks.py)
- [test_tasks.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_tasks.py)

Current behavior:

- Creates tasks in `pending`
- Supports `pending -> running -> succeeded`
- Rejects illegal transition from `succeeded` back to `running`

### Ingestion Boundary

Implemented in:

- [ingestion.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/ingestion.py)
- [test_ingestion.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_ingestion.py)

Current behavior:

- Selects only Gmail messages from configured senders with PDF attachments
- Creates a `pending` document-processing task after a successful import boundary
- Saves raw PDF attachments under `STORAGE_ROOT/raw/gmail/...`
- Persists imported document metadata for sender, message id, attachment id, content hash, and raw path
- Prevents duplicate imports for the same message id, attachment id, and content hash
- Provides a minimal batch import entrypoint that filters messages and imports matching PDF attachments

### Gmail Adapter

Implemented in:

- [gmail.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/gmail.py)
- [config/gmail-config.json](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/config/gmail-config.json:1)
- [test_gmail.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_gmail.py)

Current behavior:

- Loads Gmail Desktop OAuth settings from a JSON config file
- Supports an optional `proxy_url` and falls back to proxy environment variables when needed
- Uses a requests-based authenticated Gmail transport that works with the local VPN proxy flow
- Extracts PDF attachments from Gmail messages
- Extracts direct PDF links from message bodies
- Follows landing-page links and picks likely PDF download buttons using keyword matching
- Resolves QQ Mail landing pages by posting `f=json` and using the returned download URL
- Skips unreachable or broken body links instead of aborting the whole import run
- Normalizes Gmail API responses into the repository's existing ingestion pipeline
- Exposes a one-shot `gmail-import` management command for local import runs
- Has now been validated against a real Gmail mailbox rather than only fakes

### Database Baseline

Implemented in:

- [database.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/database.py)
- [0001_initial.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0001_initial.sql)
- [test_database.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_database.py)

Current behavior:

- Supports a Phase 1 SQLite runtime URL
- Applies a baseline schema migration on a new database
- Records applied migration versions in `schema_migrations`
- Creates initial `documents` and `processing_tasks` tables
- `documents` now stores Phase 2 import metadata needed to trace raw PDFs back to Gmail inputs

### Management Commands

Implemented in:

- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [test_manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_manage.py)

Current behavior:

- `migrate` applies pending schema migrations without starting `web` or `worker`
- `check` reports runtime readiness for a named service in JSON
- `check` can read settings from explicit CLI flags or environment variables

### Runtime Entry Points

Implemented in:

- [runtime.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/runtime.py)
- [web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/worker.py)
- [logging_utils.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/logging_utils.py)
- [test_web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_web.py)
- [test_worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_worker.py)
- [test_logging_utils.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_logging_utils.py)

Current behavior:

- `web` starts a minimal WSGI app with `GET /healthz`
- `worker` performs startup checks and emits structured JSON startup logs
- Both runtime entrypoints auto-apply pending SQLite migrations at startup
- Health and startup reports expose environment and database readiness

## Docker Runtime Skeleton

Implemented in:

- [Dockerfile](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/Dockerfile)
- [docker-compose.yml](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docker-compose.yml)
- [.env.example](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/.env.example)
- [requirements.txt](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/requirements.txt)
- [test_container_scaffolding.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_container_scaffolding.py)

Current behavior:

- Repository includes `web`, `worker`, and `db` service definitions
- `web` and `worker` now run real Python module entrypoints rather than placeholder commands
- Default container runtime uses a shared SQLite database under `/data`
- `web` and `worker` expose explicit container healthchecks through the management command
- Service startup order now uses explicit dependency conditions in Compose
- Container configuration validates with `docker compose config`
- Python runtime dependency `pypdf` is recorded for both local and container use
- A root [README.md](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/README.md) now documents local test and startup commands

This is still a scaffold, not a finished product runtime. It is now enough to boot a minimal local stack, initialize its schema explicitly, and validate service readiness in a repeatable way.

## Real PDF Sample Coverage

The following real samples are now used in automated tests:

- [/Users/pzk/workspace/NewspaperTranslator/华尔街日报-4-20.pdf](/Users/pzk/workspace/NewspaperTranslator/华尔街日报-4-20.pdf)
- [/Users/pzk/workspace/NewspaperTranslator/卫报-4-21.pdf](/Users/pzk/workspace/NewspaperTranslator/卫报-4-21.pdf)
- [/Users/pzk/workspace/NewspaperTranslator/金融时报-4-20.pdf](/Users/pzk/workspace/NewspaperTranslator/金融时报-4-20.pdf)

Implemented in:

- [pdf.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/pdf.py)
- [test_pdf_inspection.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_pdf_inspection.py)

Current behavior:

- Reports page counts for the three sample PDFs
- Detects whether a document has extractable text
- Classifies the samples as first-pass `digital` or `scanned`
- Extracts page text from digital samples
- Returns empty page text for the current scanned sample
- Builds page-level profiles for every page
- Extracts text pages only for pages with extractable text
- Extracts simple line-based text blocks from digital pages
- Extracts first-pass title candidates from digital sample pages

Current observed sample outcomes:

- `华尔街日报-4-20.pdf`: 36 pages, classified as `digital`
- `卫报-4-21.pdf`: 40 pages, classified as `digital`
- `金融时报-4-20.pdf`: 28 pages, classified as `scanned`

## Test Status

Current test command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result at the time of this summary:

```text
Ran 46 tests in 31.740s
OK
```

## Live Gmail Validation

On 2026-04-22, the Gmail import path was validated end to end against the real mailbox configuration in [config/gmail-config.json](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/config/gmail-config.json:1).

Confirmed during this session:

- Desktop OAuth token creation and reuse work locally
- Gmail API access works through the local proxy `http://127.0.0.1:7897`
- `messages.list(maxResults=1)` returns successfully against the live Gmail account
- Body-link imports now support the two observed newspaper delivery patterns
- Direct PDF delivery works for `dl.dengtazk.xin`
- QQ Mail landing-page delivery works for `wx.mail.qq.com/ftn/download?...`
- Narrowing `allowed_link_domains` to `dl.dengtazk.xin` and `wx.mail.qq.com` removes unrelated mail-body links from the import surface

Latest successful live import result:

- `fetched_message_count=25`
- `imported_attachment_count=4`
- `created_document_count=4`
- `skipped_document_count=0`

## What This Enables Next

For Phase 1, the repository now has enough behavior to treat the local runtime baseline as complete.

For Phase 2, the repository now has a genuinely working Gmail-to-raw-PDF ingestion path, which makes the next steps:

1. Persist import-run history and per-link or per-message failure details so reruns are observable.
2. Add a richer source model than storing all source metadata directly on `documents`.
3. Introduce pagination and incremental checkpointing for larger mailboxes and repeated scheduled imports.
4. Start the next Phase 2 slice after ingestion: reconstruct articles and sections from imported newspaper PDFs.

## Important Constraint

The current document-processing logic is intentionally minimal:

- Text blocks are line-based, not coordinate-aware layout blocks.
- Title candidates are heuristic and recall-oriented.
- No article reconstruction, OCR, translation, tagging, or dashboard runtime exists yet.

That is expected at this stage. The main achievement is that the repository now has both a real, tested PDF parsing entrypoint and a real, validated Gmail ingestion entrypoint grounded in live sample flows rather than only design documents.
