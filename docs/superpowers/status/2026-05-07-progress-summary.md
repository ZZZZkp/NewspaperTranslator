# Newspaper Translator Progress Summary

Date: 2026-05-07

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion is complete for the current repository goals.

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
- advertisement classification piggybacked on the translation request, with skipped articles excluded from reader surfaces

## What Was Added Since 2026-05-06

Implemented and verified in the article-throughput-and-ad-filter slice:

### Advertisement Classification

- `GeminiArticleTranslator` now returns `content_type` (`article` | `advertisement` | `uncertain`) and `classification_reason` alongside the translated title and body
- The translation prompt instructs the model to classify simultaneously with translation, treating only very obvious newspaper advertisements, sponsored/promotional blocks, subscription offers, or display-ad-like content as `advertisement`; business news, product reporting, reviews, opinion columns, company profiles, and similar content are explicitly excluded from that label
- For `article` and `uncertain`, translated title and body must be non-empty; for `advertisement`, empty translations are allowed
- `enrich_article()` branches on `content_type`: the advertisement path skips the summarizer/tagger, records all statuses as `skipped`, and finalizes the enrichment run as `skipped_advertisement`
- `process_article_processing_run` treats `skipped_advertisement` as a successful processing run so advertisements do not retry automatically

### Persistence

- Migration `0012_article_enrichment_classification` adds `content_type TEXT NOT NULL DEFAULT 'article'` and `classification_reason TEXT NOT NULL DEFAULT ''` to `article_enrichment_outputs`; existing rows default to `content_type='article'`
- `record_article_enrichment_outputs` accepts and persists both new columns
- `get_latest_article_enrichment` includes `skipped_advertisement` in its usable-status filter and returns `content_type` and `classification_reason`

### Reader-Facing Filtering

- `list_article_card_views`, `get_overview_view` (both `article_count` and `pending_article_count`), and `get_filter_options_view` exclude articles whose latest usable enrichment is `skipped_advertisement`
- `get_document_processing_detail_view` excludes `skipped_advertisement` articles from `visible_articles`
- `list_focus_tag_article_card_views` inherits the filter via delegation

### Operator Visibility

- `ArticleProcessingDetailView` now exposes `content_type`, `classification_reason`, and `latest_enrichment_status`, giving operators an audit trail for any misclassification

### Worker Throughput

- Default `ARTICLE_WORKER_CONCURRENCY` raised from 2 to 4
- New `ARTICLE_WORKER_BATCH_SIZE` setting (default 8): the article tick selects up to 8 eligible article runs per pass but the ThreadPoolExecutor is bounded by `ARTICLE_WORKER_CONCURRENCY`
- New `PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS` (default 10) and `PROCESSING_IDLE_POLL_INTERVAL_SECONDS` (default 60): the worker loop sleeps with the active interval after a tick that found work, and with the idle interval after an empty-queue tick
- `run_processing_tick` short-circuits before creating a `scheduler_run` when both document and article queues are empty, avoiding a stream of empty scheduler history

### Configuration

- `docker-compose.yml` `worker.environment` now explicitly passes `ARTICLE_WORKER_CONCURRENCY`, `DOCUMENT_WORKER_CONCURRENCY`, `ARTICLE_WORKER_BATCH_SIZE`, `PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS`, and `PROCESSING_IDLE_POLL_INTERVAL_SECONDS` with matching defaults
- `.env.example` documents the new settings under a `# Worker throughput` section

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 239 tests in 6.470s
OK
```

## Dual Worker And Article Drain Follow-up

Implemented and verified the dual-worker article drain:

### Worker Role Split

- `run_worker_loop()` reads `WORKER_ROLE` env var at startup and dispatches to `run_article_worker_loop()` when set to `"article"`; otherwise falls through to the existing import+document loop
- `run_article_worker_loop()` calls `recover_articles()` once at startup, then loops: checks a work-exists probe before calling the drain (idle probe pattern), then sleeps `ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS`
- `build_run_article_processing_tick_from_env()` and `build_article_work_exists_fn_from_env()` capture settings at build time and return zero-argument closures

### Article Processing Drain

- `run_processing_tick()` no longer handles article processing; it now handles only document processing
- `run_scheduler_tick()` likewise drops article-specific parameters — they were dead code forwarded from callers
- `run_article_processing_drain()` drives article throughput as a standalone drain — fills a `ThreadPoolExecutor` slot pool until the article queue is empty
- `manage.run_process_pending_documents_from_env()` simplified to build only document parameters

### Docker Compose

- `worker` service: sets `WORKER_ROLE=import` by default, adds `GMAIL_IMPORT_INTERVAL_SECONDS`, removes the now-unused article batch and poll-interval settings
- New `article-worker` service: `WORKER_ROLE=article`, same build/volume/depends_on config, exposes `ARTICLE_WORKER_CONCURRENCY` and `ARTICLE_WORKER_IDLE_POLL_INTERVAL_SECONDS`, includes healthcheck, no `GMAIL_CONFIG_PATH`
- `.env.example` updated accordingly

### Test File Split

`tests/test_document_processing.py` (3022 lines, 43 tests) was split into focused files to stay within tool read limits:

| New file | Contents |
|---|---|
| `tests/_document_processing_helpers.py` | `DocumentProcessingTestMixin` shared helpers + fake collaborators |
| `tests/test_scheduler_run_store.py` | Scheduler run store operations (2 tests) |
| `tests/test_document_run_store.py` | Document + article run store operations (10 tests) |
| `tests/test_process_document.py` | Document processing and article enrichment (10 tests) |
| `tests/test_process_article.py` | Article processing runs, enqueueing, stale recovery (6 tests) |
| `tests/test_drain.py` | Document and article processing drains (6 tests) |
| `tests/test_scheduler_tick.py` | Scheduler and processing tick integration (9 tests) |

Each file imports helpers via `sys.path.insert(0, ...)` since `tests/` has no `__init__.py`. Each test class inherits `DocumentProcessingTestMixin, unittest.TestCase`.

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

Current result:

```text
Ran 264 tests in 6.969s
OK
```

## Current Open Items

- Some expired `dengtazk.xin` links return `401`; recorded as link fetch failures.
- The newest article-processing workbench still needs browser-driven manual QA and a small UI polish pass.
- LLM-based cross-page continuation inference remains deferred.

## Publication Date, Dedupe, And Source Name Follow-up

- added `documents.source_message_internal_date` for first-seen Gmail metadata
- changed Gmail PDF dedupe from attachment-instance identity to `content_hash`
- resolved publication dates from month-day filenames such as `金融时报-5-6.pdf`
- changed `documents.source_name` to store filename prefixes while keeping import-audit `source_name = gmail`
- invalid numeric filename suffixes such as `-2-30` now fall back to markdown date resolution instead of blocking parse completion
- updated database migration expectations so schema tests include `0013_documents_source_metadata`

### Verification

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_database.DatabaseMigrationTests.test_applies_documents_source_metadata_schema_migration tests.test_ingestion.IngestionSelectionTests tests.test_article_pipeline.ArticlePipelineTests tests.test_gmail.GmailIntegrationTests -v`
  Result: `Ran 40 tests` -> `OK`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_document_processing tests.test_api_queries tests.test_web -v`
  Result: `Ran 81 tests` -> `OK`
