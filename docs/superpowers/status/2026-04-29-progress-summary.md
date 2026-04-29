# Newspaper Translator Progress Summary

Date: 2026-04-29

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion remains complete for the current repository goals.

Phase 3 automatic backend processing has now reached the intended first unattended milestone for this repository slice.

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

## What Was Added On 2026-04-29

Implemented in:

- [document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/worker.py)
- [test_document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_document_processing.py)
- [test_manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_manage.py)
- [test_web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_web.py)
- [test_worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_worker.py)

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

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests
```

Current result:

```text
Ran 140 tests in 4.465s
OK
```

Primary slice verification:

```bash
./.venv/bin/python -m unittest tests.test_worker tests.test_document_processing tests.test_manage tests.test_web
```

```text
Ran 57 tests in 1.320s
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

- dashboard pages
- article-level parallel enrichment
- advanced scheduling policies beyond the fixed interval
- notifications or alerting
- exact replay of every missed interval during laptop sleep
- broader parsing-quality work beyond the already approved backend automation scope

## Suggested Next Step

The approved backend automatic-processing slice is complete. The next meaningful product slice would be a dashboard or richer operator UX on top of the new CLI and web control surfaces.
