# Publication Date, PDF Dedupe, And Source Name Design

Date: 2026-05-07

Related documents:

- [Article Persistence And Enrichment Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-persistence-and-enrichment-design.md)
- [Import Enqueue And Translation Filter Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-06-import-enqueue-and-translation-filter-design.md)
- [Manual Gmail Import And Continuous Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-06-manual-gmail-import-and-continuous-processing-design.md)

## Overview

This document defines a focused fix for three production issues in the current Gmail-to-article pipeline:

1. `parse_persist` fails to resolve publication dates for filenames such as `金融时报-5-6.pdf`
2. repeated delivery of the same PDF through different Gmail messages creates duplicate documents
3. newly imported documents store `documents.source_name = gmail`, even though article and dashboard surfaces use that field as the newspaper label

The solution must preserve the current operator expectations:

- publication date is determined by the PDF filename when possible
- Gmail message date may help fill missing filename year information, but must not override the filename date
- identical PDF content should be deduplicated across messages
- the first accepted copy of a PDF remains authoritative for document metadata such as `source_name`

## Goals

- Support filename-based date extraction from both `YYYY-MM-DD` and `M-D` / `MM-DD` patterns
- Use the related Gmail message year to complete yearless filename dates
- Keep filename date resolution authoritative over Gmail date resolution
- Deduplicate imported PDFs by file content rather than message identity
- Store the newspaper prefix from the filename in `documents.source_name`
- Keep Gmail import audit tables using `gmail` as the import source
- Avoid unnecessary reparsing or re-enqueueing when a duplicate PDF arrives again

## Non-Goals

- Retrofitting or merging all historical duplicate documents already stored in the database
- Replacing filename-based publication date rules with Gmail date rules
- Introducing a new generalized publisher registry or source normalization layer
- Changing article-facing source labels to standardized English or Chinese names

## Current Problem

### 1. Publication date resolution is too narrow

`persist_document_articles` currently resolves publication date from:

1. an ISO-like date embedded in `documents.original_filename`
2. a written English date in MinerU markdown
3. an ISO-like date embedded in MinerU markdown

This works for `wsj-2026-04-20.pdf` but fails for filenames such as `金融时报-5-6.pdf`, because the parser does not support month-day filenames without a year.

### 2. Document identity is tied to message identity

Gmail imports currently create `document_key` values from `message_id`, `attachment_id`, and `content_hash`. The `documents` insert is therefore keyed by one email attachment instance, not by the actual PDF content. If the same PDF is forwarded again in another message, the system creates a second document and a second processing run.

### 3. `documents.source_name` has the wrong meaning

The current Gmail ingestion code writes `documents.source_name = gmail`. That matches import provenance, but article queries, filters, and frontend cards treat `documents.source_name` as the newspaper label. This produces incorrect UI and filtering semantics.

## Design Principles

- Keep import provenance and document newspaper label as separate concepts
- Prefer explicit, local document metadata over indirect reconstruction from audit history
- Keep duplicate-content handling deterministic and idempotent
- Preserve current successful flows for complete filename dates and markdown fallback dates
- Do not silently override filename-derived dates with Gmail dates

## Data Model

### `documents`

The `documents` table keeps its existing role as the durable raw-document registry, but two semantics change:

- `source_name` means the filename-derived newspaper prefix, not the transport source
- a new nullable `source_message_internal_date` field stores the Gmail message timestamp associated with the first accepted copy of the document

Recommended schema changes:

- add `source_message_internal_date TEXT`
- add an index on `content_hash`

This design intentionally does not require a historical backfill or merge of existing duplicate rows.

### Import audit tables

`import_runs.source_name`, `failed_messages.source_name`, and any import-audit usage of `source_name` continue to mean import transport and remain `gmail`.

This preserves the current checkpointing and retry model.

## Source Name Extraction

`documents.source_name` should be derived from the filename prefix.

Rule:

1. remove directory components
2. remove the file extension
3. identify the trailing date segment
4. store the leading prefix before that date segment

Examples:

- `金融时报-5-6.pdf` -> `金融时报`
- `FT-5-6.pdf` -> `FT`
- `wsj-2026-05-06.pdf` -> `wsj`

If the same PDF content is imported again under a different filename prefix, the first accepted document keeps its original `source_name`. Later duplicate sightings do not overwrite it.

If no trailing date segment can be identified, ingestion should use the full filename stem as `source_name`. If stripping the detected date segment would leave an empty prefix, ingestion should also fall back to the full filename stem. The fallback must stay deterministic and test-covered.

## Publication Date Resolution

Publication date remains required metadata and continues to be stored as `YYYY-MM-DD`.

### Resolution priority

1. Parse a full date from `documents.original_filename`
2. Parse month-day from `documents.original_filename` and fill the year
3. Parse a written English date from MinerU markdown
4. Parse an ISO-like date from MinerU markdown
5. Fail the parse run if no valid date can be resolved

### Supported filename patterns

The filename resolver must support:

- `YYYY-MM-DD`
- `YYYY_M_D`
- `M-D`
- `MM-DD`
- equivalent separators already accepted by the current ISO matcher

Examples:

- `wsj-2026-05-06.pdf` -> `2026-05-06`
- `金融时报-5-6.pdf` -> month `5`, day `6`, year still unresolved at this step

### Year completion for month-day filenames

When the filename contains only month and day:

1. use the year from `documents.source_message_internal_date` if present
2. otherwise use the current runtime year

Example:

- filename: `金融时报-5-6.pdf`
- Gmail message timestamp: `2026-05-07T...`
- resolved publication date: `2026-05-06`

### Authority and conflicts

Filename resolution is authoritative.

- If the filename resolves to `2026-05-06` and Gmail date is `2026-05-07`, the final publication date remains `2026-05-06`
- Gmail date is only a year-completion helper and optional warning source
- filename/Gmail disagreement should be logged but must not block processing

### Invalid date handling

Invalid filename dates such as `2-30` or `13-1` must fail parse resolution. The system must not silently replace invalid filename dates with Gmail dates.

## Duplicate PDF Handling

Duplicate handling changes from attachment-instance dedupe to content dedupe.

### Import flow

For every accepted PDF attachment:

1. compute `content_hash`
2. look up an existing row in `documents` by `content_hash`
3. if no row exists:
   - create a new document
   - store filename-derived `source_name`
   - store `source_message_internal_date` from the Gmail message when available
   - write the raw PDF if missing
   - ensure a `document_processing_run` exists
4. if a row already exists:
   - reuse the existing `document_key`
   - do not create a second `documents` row
   - do not create a second raw file path
   - do not enqueue a second processing run if one already exists

This keeps repeated forwarding of the same PDF idempotent.

### Authority of first accepted copy

When duplicate content is found, the first accepted document remains authoritative for:

- `document_key`
- `source_name`
- `original_filename`
- `source_message_internal_date`

Later imports are treated as duplicate sightings only. They may be recorded in audit history, but they do not mutate the canonical document row.

## Components And Boundaries

### `src/newspaper_translator/ingestion.py`

Responsibilities after this change:

- derive `content_hash`
- derive filename-prefix `source_name`
- look up existing documents by `content_hash`
- create or reuse a canonical document row
- persist `source_message_internal_date` on first insert
- continue to ensure one `document_processing_run` exists for the canonical document

### `src/newspaper_translator/article_pipeline.py`

Responsibilities after this change:

- read richer document context, including `source_message_internal_date`
- resolve publication date through a dedicated helper
- keep markdown fallback behavior
- fail explicitly when no valid date can be resolved

The date resolver should be structured as a focused helper rather than more ad hoc regex logic embedded inside `persist_document_articles`.

## Data Flow

### New document import

`Gmail message -> attachment -> content_hash -> no existing document -> insert documents row with filename prefix + Gmail message internal date -> ensure processing run -> parse_persist resolves publication date -> final articles persist`

### Duplicate document import

`Gmail message -> attachment -> content_hash -> existing document found -> reuse canonical document_key -> record audit result -> do not create duplicate document row -> do not create duplicate processing run`

### Yearless filename parse

`documents.original_filename = 金融时报-5-6.pdf -> extract prefix 金融时报 -> extract month/day 5/6 -> read documents.source_message_internal_date -> take year 2026 -> resolve publication_date = 2026-05-06`

## Error Handling

- Missing filename date and missing markdown date: fail parse run
- Month-day filename with unavailable Gmail date: use current runtime year
- Invalid filename date: fail parse run
- Filename date and Gmail date disagree: log a warning, continue with filename date
- Duplicate content import: succeed without creating duplicate durable document state

## Logging

Add structured logs for:

- publication date resolution source, such as `filename_full`, `filename_month_day_gmail_year`, `markdown_written`, `markdown_iso`
- filename/Gmail date disagreement warnings
- duplicate-content reuse decisions, including canonical `document_key`

These logs should make future operator debugging possible without reading code.

## Testing

### Date resolution tests

- `金融时报-5-6.pdf` plus Gmail date `2026-05-07` resolves to `2026-05-06`
- `金融时报-05-06.pdf` resolves the same way
- `金融时报-5-6.pdf` without Gmail date falls back to runtime year
- `金融时报-2-30.pdf` fails
- filename without date plus markdown `May 6, 2026` succeeds
- existing `wsj-2026-04-20.pdf` behavior remains unchanged

### Source name tests

- `金融时报-5-6.pdf` stores `documents.source_name = 金融时报`
- `FT-5-6.pdf` stores `documents.source_name = FT`
- `wsj-2026-05-06.pdf` stores `documents.source_name = wsj`

### Duplicate handling tests

- same message and same attachment imported twice still produces one document
- different messages with identical PDF bytes produce one canonical document
- duplicate-content reimport does not create a second `document_processing_run`
- duplicate-content reimport does not overwrite the first document's `source_name`
- duplicate-content reimport does not overwrite the first document's `original_filename`

### Audit behavior tests

- import audit continues to record `source_name = gmail`
- duplicate-content reimport records a distinguishable audit outcome that points at the reused `document_key`

## Migration Strategy

This change should be implemented with a small forward-only migration:

1. add `documents.source_message_internal_date`
2. add an index on `documents.content_hash`

This design does not require automatic cleanup of already duplicated historical documents. Any such cleanup would be a separate maintenance task because it would need to reconcile parse runs, processing runs, and downstream article history.

## Acceptance Criteria

- `parse_persist` no longer fails for `金融时报-5-6.pdf` when the related Gmail message year is available
- the resolved publication date for that file is `2026-05-06`
- duplicate PDF content sent through later Gmail messages does not create a new canonical document
- repeated duplicate imports do not create duplicate processing runs
- document-facing APIs and filters expose filename-prefix `source_name` values instead of `gmail`
- import-audit APIs continue to expose `gmail` as the import source
