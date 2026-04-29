# Newspaper Translator Progress Summary

Date: 2026-04-29

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion remains complete for the current repository goals.

Phase 3 automatic backend processing remains at the intended first unattended milestone for the backend slice.

The repository has now also started the first product-facing dashboard slice on top of that backend.

The repository currently provides:

- a working Gmail-to-raw-PDF import path
- durable import-run and item-level audit history
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, lineage, and enrichment persistence
- a long-running worker loop with overdue catch-up scheduling
- automatic document-level parse and enrich execution through one shared control-plane path
- document-level parallel processing inside one scheduler tick
- CLI operator surfaces for manual scheduler execution, manual retry, and document-processing inspection
- backend-only web surfaces for listing document-processing state, reading one document state, and requesting retry
- structured scheduler, document, and retry lifecycle logs
- aggregated dashboard query surfaces for overview, article cards, article detail, filters, and focus-tag article feeds
- a first standalone `frontend/` dashboard shell packaged as a separate service in Docker Compose
- a browser-rendered dashboard home with summary cards, filter controls, focus-tag cards, and full article cards
- a first browser-rendered article detail view with Chinese, English, and compare modes
- a browser-rendered operator workbench for document-processing list and document detail flows
- document detail bridge content showing visible articles, document identity, and failure summaries
- Docker Compose defaults that avoid host-port conflicts for local databases while keeping frontend and web ports configurable

## What Was Added On 2026-04-29

Implemented in:

- [queries.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/api/queries.py)
- [document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- [frontend/index.html](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/index.html)
- [frontend/styles.css](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/styles.css)
- [frontend/app.js](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/app.js)
- [frontend/Dockerfile](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/Dockerfile)
- [frontend/nginx.conf](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/nginx.conf)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/worker.py)
- [test_api_queries.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_api_queries.py)
- [test_document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_document_processing.py)
- [test_frontend_static.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_frontend_static.py)
- [test_manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_manage.py)
- [test_web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_web.py)
- [test_worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_worker.py)
- [docker-compose.yml](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docker-compose.yml)
- [.env.example](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/.env.example)

Current behavior:

- `worker.py` now runs a real long-lived scheduler loop instead of only sleeping after startup
- worker startup runs stale-run recovery and one immediate catch-up tick when the scheduler is overdue
- the shared scheduler runtime now uses real Gmail import plus real parse/enrich orchestration from environment-backed runtime wiring
- one scheduler tick can now process multiple eligible documents concurrently while keeping single-document step order sequential
- `scheduler-run-once` triggers one manual scheduler tick from the CLI
- `process-pending-documents` processes the current eligible document set without requiring a Gmail import run
- `retry-document --document-key ...` reactivates one document for manual retry through the CLI
- `document-processing-status --document-key ...` returns the current control-plane state for one document through the CLI
- `GET /document-processing` lists current document-processing runs with optional status filtering
- `GET /document-processing/<document_key>` returns one document-processing run
- `POST /document-processing/<document_key>/retry` requests manual retry through the web backend
- scheduler ticks now emit structured JSON lifecycle logs for tick start, Gmail import start/finish, and tick finish
- document orchestration now emits structured JSON logs for claim, step start/finish, immediate retry scheduling, stale recovery, failure-state transitions, and manual retry requests
- `GET /api/overview` returns dashboard summary counts for imported documents, visible articles, running documents, and pending exceptions
- `GET /api/articles` returns article-card payloads and now supports `source`, `tag`, `publication_date_from`, and `publication_date_to`
- `GET /api/articles/<article_id>` returns bilingual article detail payloads plus lightweight processing context
- `GET /api/filters` returns distinct source and tag values for dashboard filter controls
- `GET /api/focus-tags/articles` returns article cards matching `FOCUS_TAGS` from environment configuration
- `frontend/app.js` now renders a dashboard home by calling the new read APIs through an Nginx reverse-proxy container
- dashboard article cards are clickable and open an in-page article detail view through `#article/<article_id>` hash routing
- the article detail view now supports Chinese, English, and compare modes without leaving the frontend shell
- the standalone frontend now includes a document-processing list view plus a document detail page with retry actions
- article detail can now jump directly to the source document detail page
- document detail now shows current visible article cards, document identity fields, and a compact latest-error summary
- `/api/document-processing/<document_key>` now returns a UI-ready detail payload rather than only the raw processing run fields
- Docker Compose now keeps `db` on the internal Compose network by default while letting `FRONTEND_PORT` and `WEB_PORT` override host bindings

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest tests.test_api_queries tests.test_web tests.test_frontend_static tests.test_container_scaffolding -v
```

Current result:

```text
Ran 42 tests in 1.166s
OK
```

Primary slice verification:

```bash
./.venv/bin/python -m unittest tests.test_api_queries tests.test_web tests.test_frontend_static tests.test_container_scaffolding -v
```

```text
Ran 42 tests in 1.166s
OK
```

## Automatic-Processing Snapshot

Completed automatic-processing slices so far:

- durable scheduler-run and document-processing control-plane persistence
- single-document safe claim and eligible-document priority ordering
- step-level immediate retry and automatic failure-state transitions
- manual retry reactivation and status inspection
- real parse-persist and document-level enrichment orchestration
- stale-running recovery and overdue catch-up scheduling
- full long-running worker loop integration
- document-level parallel execution inside one scheduler tick
- CLI operator entrypoints for manual triggering and inspection
- backend-only web endpoints for retry and status reads
- structured scheduler/document lifecycle logging

Still intentionally out of scope:

- frontend article detail route as a dedicated standalone page outside the current single-shell hash-routing approach
- article-level parallel enrichment
- advanced scheduling policies beyond the fixed interval
- notifications or alerting
- exact replay of every missed interval during laptop sleep
- broader parsing-quality work beyond the already approved backend automation scope

## Suggested Next Step

The next meaningful product slice is to polish the operator workflow further by improving document-list scanability and adding clearer action guidance for retryable, running, and succeeded document states.
