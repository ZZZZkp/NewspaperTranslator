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
- scheduler-driven article-stage execution and stale-run recovery
- dedup-aware enrichment reuse for unchanged logical articles based on stable content `input_hash`
- article-stage CLI and web/API entry points for status inspection and manual retry

## What Was Added On 2026-04-30

Implemented in:

- [api/queries.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/api/queries.py)
- [article_enrichment.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_enrichment.py)
- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
- [document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/worker.py)
- [web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [0008_article_fragment_page_numbers.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0008_article_fragment_page_numbers.sql)
- [0009_final_articles_article_key.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0009_final_articles_article_key.sql)
- [0010_article_processing_runs.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0010_article_processing_runs.sql)
- [test_api_queries.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_api_queries.py)
- [test_article_enrichment.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_article_enrichment.py)
- [test_article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_article_store.py)
- [test_database.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_database.py)
- [test_document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_document_processing.py)
- [test_manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_manage.py)
- [test_web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_web.py)
- [test_worker.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_worker.py)

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
- worker startup and scheduler ticks now recover stale article-stage work and execute pending article enrichment independently of document retries
- automatic article enqueue now compares the current logical article input hash against the last successful hash for that `article_key`
- unchanged logical articles now stay out of automatic re-enqueue, while changed logical articles are reset to `pending`
- `enrich_article(...)` now reuses an existing successful enrichment run for unchanged input instead of writing a duplicate success row
- manual article retry still bypasses the dedup guard and forces a fresh enrichment attempt
- CLI now supports `retry-article` and `article-processing-status`
- web/API now supports article-stage list, detail, and manual retry entry points through `/api/article-processing`
- article-stage detail queries now expose article title, source filename, publication date, page numbers, and latest error summary for operator troubleshooting

## Current Test Status

Current command:

```bash
python3 -m unittest tests.test_manage tests.test_api_queries tests.test_web tests.test_article_enrichment tests.test_document_processing tests.test_article_store tests.test_database tests.test_worker
```

Current result:

```text
Ran 112 tests in 3.053s
OK
```

Key new TDD verification added today:

- migration test proving `article_fragments.page_number` exists before implementation
- store test proving persisted fragment page numbers and article source page lists are readable
- store test proving repeated parses of the same source file can reuse `article_key`
- database and processing tests proving `article_processing_runs` exists and supports current-state transitions
- document-processing tests proving parse success now leaves the document `succeeded` while article-stage work is enqueued independently
- worker tests proving article-stage work is wired into startup recovery and scheduler execution
- enrichment tests proving unchanged repeated parses reuse a prior successful run instead of creating duplicate success history
- processing tests proving only changed logical articles are automatically re-enqueued after a repeated parse
- management command tests proving article-stage manual retry and status commands are wired correctly
- web and query tests proving article-stage list/detail/retry endpoints return the expected operator context

## Article-Stage Retry Snapshot

Completed slices from the approved article-stage retry plan so far:

- source page metadata persistence
- logical article identity persistence
- article-stage processing persistence
- document success decoupled from synchronous article enrichment success
- dedup-aware enqueue and reuse rules based on successful current input hashes
- automatic scheduler execution of `article_processing_runs`
- article-stage API and CLI retry surfaces

Not completed yet in this milestone:

- frontend display of article source filename and page numbers
- frontend operator views for article-stage exceptions

## Suggested Next Step

The next meaningful slice is to wire these article-stage endpoints into the operator workbench so failures, source-page metadata, and retry actions are visible directly in the frontend.
