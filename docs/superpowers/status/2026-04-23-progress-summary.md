# Newspaper Translator Progress Summary

Date: 2026-04-23

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 now has a durable Gmail ingestion slice rather than only a one-shot importer.

The repository currently provides:

- a working Gmail-to-raw-PDF import path
- persisted import-run and item-level audit history
- read-only CLI and web query surfaces for import-run inspection
- time-window incremental checkpointing for repeated Gmail imports
- automatic and manual retry flows for unresolved failed Gmail messages
- top-level retry and checkpoint summary fields on `import-runs`

## What Was Added On 2026-04-23

Implemented in:

- [import_audit.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/import_audit.py)
- [gmail.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/gmail.py)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [0002_import_audit.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0002_import_audit.sql)
- [0003_checkpointing_retry.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0003_checkpointing_retry.sql)
- [0004_import_run_retry_summary.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0004_import_run_retry_summary.sql)

Current behavior:

- `gmail-import` records each import run and each processed item
- `gmail-import-runs`, `gmail-import-run-items`, and `gmail-import-items` expose audit data from the CLI
- `/import-runs`, `/import-runs/<run_id>`, `/import-runs/<run_id>/items`, and `/import-items` expose the same state over HTTP
- successful or partial Gmail imports advance a persisted time-based checkpoint
- failed Gmail messages are tracked separately from item-level failures so they can be retried after the checkpoint moves forward
- each unresolved failed message gets at most one retry attempt
- a message is marked resolved only after all previously failed items for that message succeed
- parent import runs now expose whether a retry happened and how many messages were retried, resolved, or left in `failed_final`

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 64 tests in 30.644s
OK
```

## Phase 2 Snapshot

Completed Phase 2 slices so far:

- Gmail attachment import into raw PDF storage
- body-link import for direct PDF links and QQ Mail landing pages
- durable audit history for runs and items
- incremental checkpointing for repeated imports
- failed-message retry orchestration
- retry/checkpoint visibility on import-run query surfaces

Still not implemented:

- a richer source or source-item model beyond document-level import metadata
- article and section reconstruction from imported newspaper PDFs
- OCR for scanned PDFs
- enrichment, review, and dashboard features

## Suggested Next Step

The next Phase 2 milestone should move beyond ingestion mechanics and start shaping imported inputs into a richer source model that can support article reconstruction and downstream processing.
