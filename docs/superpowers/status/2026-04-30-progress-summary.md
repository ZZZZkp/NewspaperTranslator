# Newspaper Translator Progress Summary

Date: 2026-04-30

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion remains complete for the current repository goals.

Phase 3 backend processing has now moved into the first article-stage retry refactor milestone.

The repository currently provides:

- a working Gmail-to-raw-PDF import path
- durable import-run and item-level audit history
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, image, and enrichment persistence
- a long-running worker loop with overdue catch-up scheduling
- document-level parse persistence through one shared control-plane path
- dashboard and operator workbench product surfaces from the previous milestone
- durable fragment page-number persistence for article source tracing
- durable logical `article_key` identity across repeated parses of the same source document lineage
- a new article-stage processing control plane for enrichment work
- document processing that now enqueues article work instead of treating article enrich failure as a document-level retry condition

## What Was Added On 2026-04-30

Implemented in:

- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
- [document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- [0008_article_fragment_page_numbers.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0008_article_fragment_page_numbers.sql)
- [0009_final_articles_article_key.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0009_final_articles_article_key.sql)
- [0010_article_processing_runs.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0010_article_processing_runs.sql)
- [test_article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_article_store.py)
- [test_database.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_database.py)
- [test_document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_document_processing.py)

Current behavior:

- `article_fragments` now persists `page_number`
- `StoredArticleFragment` now exposes `page_number`
- `StoredFinalArticle` now exposes `source_page_numbers`
- `record_parse_run_result(...)` now writes fragment page numbers into storage
- `final_articles` now persists `article_key`
- new final articles can now inherit an existing `article_key` when they belong to the same document lineage, share source-page overlap, and have highly similar normalized title or article opening text
- `article_processing_runs` now provides a durable current-state table for article-stage enrichment work
- article-stage helpers now exist for:
  - create or refresh one article processing item
  - claim one article safely without double claim
  - list eligible article work with `manual_retry_requested` priority
  - mark article work `failed_retryable` or `failed_terminal`
  - mark article work `succeeded`
  - request manual article retry
- `process_document(...)` now treats `parse_persist` success as the document-stage completion boundary
- after parse success, document processing now enqueues article-stage work instead of synchronously executing article enrichment
- a failed or still-pending article enrich path no longer causes the document itself to become `failed_retryable`

## Current Test Status

Current command:

```bash
python3 -m unittest tests.test_document_processing tests.test_article_store tests.test_database tests.test_gemini
```

Current result:

```text
Ran 46 tests in 0.995s
OK
```

Key new TDD verification added today:

- migration test proving `article_fragments.page_number` exists before implementation
- store test proving persisted fragment page numbers and article source page lists are readable
- store test proving repeated parses of the same source file can reuse `article_key`
- database and processing tests proving `article_processing_runs` exists and supports current-state transitions
- document-processing tests proving parse success now leaves the document `succeeded` while article-stage work is enqueued independently

## Article-Stage Retry Snapshot

Completed slices from the approved article-stage retry plan so far:

- source page metadata persistence
- logical article identity persistence
- article-stage processing persistence
- document success decoupled from synchronous article enrichment success

Not completed yet in this milestone:

- automatic scheduler execution of `article_processing_runs`
- dedup-aware enqueue and reuse rules based on successful current input hashes
- article-stage API and CLI retry surfaces
- frontend display of article source filename and page numbers
- frontend operator views for article-stage exceptions

## Suggested Next Step

The next meaningful backend slice is to extend scheduler execution so it automatically claims and runs `article_processing_runs`, including retry ceilings and later dedup-aware reuse of successful unchanged enrichment input.
