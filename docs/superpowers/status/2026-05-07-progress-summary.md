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

## Current Open Items

- Some expired `dengtazk.xin` links return `401`; recorded as link fetch failures.
- The newest article-processing workbench still needs browser-driven manual QA and a small UI polish pass.
- LLM-based cross-page continuation inference remains deferred.
