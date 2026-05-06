# Newspaper Translator Progress Summary

Date: 2026-05-06

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion is complete for the current repository goals, including the newer body-link formats introduced by the current newspaper feed.

Phase 3 backend processing remains on the document-stage plus article-stage control-plane model:

- document processing imports and parses source PDFs into durable article records
- article processing handles translation, summary, tagging, retry, stale-run recovery, and input-hash reuse independently from document parsing

The repository currently provides:

- Gmail-to-raw-PDF import with durable import-run and item-level audit history
- incremental checkpointing and failed-message retry
- body-link imports for direct PDF URLs, QQ Mail landing pages, and `dengtazk.xin:8282` email-download links
- stable short body-link attachment IDs so long signed URLs do not become storage filenames
- conservative translated-PDF filename filtering with skipped audit records, including `【译】` prefixes and percent-encoded body-link basenames
- import-time enqueueing into `document_processing_runs` so new Gmail documents are visible to the continuous processing tick
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, image, lineage, enrichment, and article-processing persistence
- durable logical `article_key` identity across repeated parses of the same source document lineage
- scheduler-driven document and article processing with stale-run recovery
- split worker scheduling: Gmail import remains interval-driven while document/article processing polls queued work continuously
- CLI and web/API entry points for import audit, parsing debug views, document-processing retry/status, and article-processing retry/status
- manual Gmail import from the operator workbench through `POST /api/gmail/import`
- direct Gemini API mode and OpenAI-compatible gateway mode
- a standalone frontend reading dashboard with document-processing and article-processing operator workbench views

## What Was Added Since 2026-05-02

Implemented and verified in the Gmail body-link slice:

- body-link imports now use `_body_link_attachment_id` values shaped as `link:body-{hash24}`
- long signed body-link URLs no longer leak into raw-storage filenames
- `dengtawaikan@dengtazk.xin` is accepted as an allowed sender
- `www.dengtazk.xin` is accepted as an allowed link domain
- direct `dengtazk.xin:8282` PDF responses are supported
- preview pages with static script resource values such as `pdfUrl` can resolve to underlying PDF resources
- known translated-PDF filename patterns are skipped and recorded with `detail_code="body_link_filename_filtered"`

Live CLI verification on 2026-05-03:

- fetched 25 messages
- created 6 documents
- produced no path-length failures
- recorded two expired `dengtazk.xin` signed URLs as upstream `401 Client Error` failures

Implemented on 2026-05-06:

- Docker Compose now mounts `./secrets` as writable for `web` and `worker`
- this allows Google OAuth token refresh to write back to `secrets/gmail-token.json`
- the container scaffolding test now guards against accidentally restoring a read-only secrets mount
- the local Docker stack was restarted with `WEB_PORT=8015` and `FRONTEND_PORT=3002`
- worker orchestration was split into an import cadence and a processing cadence
- Gmail import now uses import-run history for its 2-hour catch-up decision
- document and article processing now run through a processing-only tick so queued work is not blocked behind the Gmail interval
- the processing-only CLI path now handles both document and article queues without faking a Gmail import
- the web API now exposes `POST /api/gmail/import` for manual Gmail fetches
- the frontend processing workbench now exposes `立即拉取邮件`
- frontend Nginx now uses a 300-second `/api/` proxy timeout after manual Gmail import initially hit a proxy `504`
- Gmail attachment imports now create or repair idempotent `document_processing_runs` rows at the import boundary, replacing the old `processing_tasks` enqueue path
- retrying the same Gmail attachment repairs a missing processing run if an earlier enqueue failed after the document metadata commit
- the `【译】` translated-PDF prefix is now filtered by basename for direct attachments and body links
- percent-encoded body-link filenames are URL-decoded before translated-filename filtering, so encoded `【译】...pdf` URLs are skipped consistently
- migration `0011_drop_processing_tasks` backfills missing `document_processing_runs` rows for existing documents before dropping the legacy `processing_tasks` table
- the unused `newspaper_translator.tasks` module and its tests were removed

Live Docker verification on 2026-05-06 after the import/enqueue fix:

- Docker `web` and `worker` were healthy with `WEB_PORT=8017`
- container schema had 11 applied migrations and `processing_tasks` was absent
- direct `POST http://127.0.0.1:8017/api/gmail/import` returned `status=succeeded`
- the live import fetched 6 messages, imported 2 attachments, created 0 new documents, and skipped 2 duplicates
- `documents.original_filename LIKE '【译】%'` returned 0 rows
- every imported document had a corresponding `document_processing_runs` row

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 218 tests in 6.817s
OK
```

Additional runtime checks on 2026-05-06:

- `web` health endpoint returned `status=ok`
- `frontend` returned the dashboard HTML
- `worker` restarted without the previous `Read-only file system: '/app/secrets/gmail-token.json'` error
- Docker inspect confirmed `/app/secrets RW=true` inside `newspapertranslator-worker-1`
- direct `POST http://127.0.0.1:8015/api/gmail/import` returned `status=succeeded`
- proxied `POST http://127.0.0.1:3000/api/gmail/import` returned `200 OK` after the Nginx timeout increase
- Docker services were running with `frontend` on port `3000`, `web` on port `8015`, and `worker` healthy
- the import/enqueue fix was also verified with `web` on port `8017` and container proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`) present

## Current Open Items

- Some expired `dengtazk.xin` links return `401`; these are recorded as link fetch failures unless future operator experience needs more specific detail codes.
- The newest article-processing workbench still needs browser-driven manual QA and a small UI polish pass.
- LLM-based advertisement/statement filtering and non-explicit cross-page continuation inference remain deferred.
