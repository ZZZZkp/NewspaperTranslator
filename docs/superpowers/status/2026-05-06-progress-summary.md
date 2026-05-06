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
- conservative translated-PDF filename filtering with skipped audit records
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, image, lineage, enrichment, and article-processing persistence
- durable logical `article_key` identity across repeated parses of the same source document lineage
- scheduler-driven document and article processing with stale-run recovery
- CLI and web/API entry points for import audit, parsing debug views, document-processing retry/status, and article-processing retry/status
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

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 205 tests in 7.706s
OK
```

Additional runtime checks on 2026-05-06:

- `web` health endpoint returned `status=ok`
- `frontend` returned the dashboard HTML
- `worker` restarted without the previous `Read-only file system: '/app/secrets/gmail-token.json'` error
- Docker inspect confirmed `/app/secrets RW=true` inside `newspapertranslator-worker-1`

## Current Open Items

- The production-like filenames `【译】华尔街日报` and `【译】金融时报` have been observed but are not yet part of the conservative translated-PDF filter list.
- Some expired `dengtazk.xin` links return `401`; these are recorded as link fetch failures unless future operator experience needs more specific detail codes.
- The newest article-processing workbench still needs browser-driven manual QA and a small UI polish pass.
- LLM-based advertisement/statement filtering and non-explicit cross-page continuation inference remain deferred.
