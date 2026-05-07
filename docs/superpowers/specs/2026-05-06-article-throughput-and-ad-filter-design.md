# Article Throughput And Advertisement Filter Design

Date: 2026-05-06

Related documents:

- [Article Stage Retry And Identity Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-30-article-stage-retry-design.md)
- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)
- [Manual Gmail Import And Continuous Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-06-manual-gmail-import-and-continuous-processing-design.md)
- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)

## Overview

Article processing is currently correct but too conservative for daily newspaper throughput. The worker defaults to a small article concurrency, each non-advertisement article still requires two Gemini requests, and a shorter processing poll interval would create noisy empty `scheduler_runs` if applied directly to the current loop.

This design improves throughput while preserving the existing durable article-stage boundary. It also adds advertisement filtering before translation finishes, without adding an extra model request.

## Goals

- Raise default article enrichment concurrency to 4.
- Let each processing tick claim enough queued article work to keep the worker busy.
- Avoid creating `scheduler_runs` when the document and article queues are empty.
- Use a fast active poll interval while work is available, and a slower idle interval after empty queue checks.
- Add advertisement classification to the existing translation request, not as a third Gemini call.
- Skip summary/tag generation for clear advertisements.
- Hide skipped advertisements from reader-facing dashboard surfaces.
- Keep skipped advertisements visible in operator processing views.

## Non-Goals

- Merging translation, summary, and tagging into one Gemini call.
- Building a separate advertisement classifier service.
- Classifying borderline newspaper content aggressively.
- Removing advertisement rows from parse history.
- Changing MinerU parsing behavior.

## Product Decisions

- Use the current two-stage enrichment shape for normal articles:
  - classification plus translation
  - summary plus tags
- Do not add a separate Gemini request for advertisement detection.
- Treat only very obvious newspaper advertisements, sponsored/promotional blocks, or display-ad-like content as advertisements.
- Treat uncertain content as an article and continue normal enrichment.
- Mark advertisement skips as successful article processing so they do not retry automatically.
- Exclude advertisement skips from reading surfaces, but retain them in operator views for traceability.

## Worker Throughput Design

### Configuration

Worker configuration should expose these settings:

- `ARTICLE_WORKER_CONCURRENCY`, default `4`
- `DOCUMENT_WORKER_CONCURRENCY`, default remains `2`
- `ARTICLE_WORKER_BATCH_SIZE`, default `8`
- `PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS`, default `10`
- `PROCESSING_IDLE_POLL_INTERVAL_SECONDS`, default `60`

`docker-compose.yml` should pass the worker concurrency and poll settings through explicitly. This makes local Compose behavior match the code defaults and avoids invisible configuration drift.

### Claiming More Work Than Concurrency

The article worker should fetch up to `ARTICLE_WORKER_BATCH_SIZE` eligible article runs per processing pass, while still executing at most `ARTICLE_WORKER_CONCURRENCY` article requests at the same time.

For example, with concurrency 4 and batch size 8:

- one tick can select up to 8 eligible article rows
- the thread pool runs 4 at once
- as a thread finishes, the next selected article starts
- the Gemini upstream sees at most 4 concurrent article enrichment attempts from this worker process

This keeps the worker busy without turning the batch size into an unbounded model-request fan-out.

### Empty Queue Behavior

The processing loop should perform a lightweight queue check before creating a `scheduler_run`.

If there is no eligible document work and no eligible article work:

- do not create a `scheduler_run`
- do not write processing history
- sleep with the idle interval

If any eligible work exists:

- create a `scheduler_run`
- process selected document and article work
- sleep with the active interval

This keeps active processing responsive while avoiding a stream of empty scheduler records.

### Scheduler History

`scheduler_runs` should continue to represent real processing attempts. A no-op queue check is operationally useful but should not become durable run history.

## Advertisement Classification Design

### Translation Response Shape

`GeminiArticleTranslator` should change from returning only translation fields to returning classification plus translation:

```json
{
  "content_type": "article",
  "classification_reason": "This is a regular newspaper article, not an advertisement.",
  "translated_title_zh": "...",
  "translated_body_zh": "..."
}
```

Allowed `content_type` values:

- `article`
- `advertisement`
- `uncertain`

For `article` and `uncertain`, `translated_title_zh` and `translated_body_zh` are required and must be non-empty.

For `advertisement`, translation fields may be empty because the article processing flow will skip summary and tagging.

### Prompt Requirements

The translation prompt must clearly state:

- the source text comes from parsed newspaper pages
- most parsed items should be treated as normal newspaper content
- only very obvious advertisements, sponsored/promotional blocks, subscription offers, display ads, or advertorial blocks should be classified as `advertisement`
- business news, market coverage, product reporting, reviews, opinion columns, book reviews, real-estate reporting, job-market reporting, or company profiles are not advertisements merely because they mention products, companies, prices, or services
- when uncertain, return `uncertain` and provide the translation
- return JSON only, with no Markdown fences or explanations outside JSON

This conservative threshold prevents ordinary newspaper journalism from being hidden.

### Enrichment Flow

`enrich_article()` should branch after the translation/classification call.

For `article` or `uncertain`:

- call the existing summary/tagger
- record translation, summary, and tags as today
- finalize the enrichment run as `succeeded` or `partial` according to existing behavior

For `advertisement`:

- do not call the summary/tagger
- record an enrichment output with:
  - `content_type = advertisement`
  - `classification_reason`
  - `translation_status = skipped`
  - `summary_status = skipped`
  - `tagging_status = skipped`
  - no tags
- finalize the enrichment run as `skipped_advertisement`
- mark the article processing run as `succeeded` with `current_step = completed` and the current input hash

Invalid Gemini JSON, missing classification fields, or empty required translations for non-advertisements should remain retryable failures.

## Persistence Design

Add a migration to persist classification metadata on enrichment output rows:

- `article_enrichment_outputs.content_type TEXT NOT NULL DEFAULT 'article'`
- `article_enrichment_outputs.classification_reason TEXT NOT NULL DEFAULT ''`

`article_enrichment_runs.status` should allow `skipped_advertisement` as a usable terminal status.

Existing rows should behave as `content_type = article`. This keeps existing dashboard and detail pages compatible.

## Reader-Facing Filtering

Reader-facing APIs should exclude articles whose latest usable enrichment is `skipped_advertisement`.

This applies to:

- overview reading counts where they represent visible articles
- `/api/articles`
- `/api/focus-tags/articles`
- document detail visible article lists
- filter tag/source options where joins would otherwise include advertisement-only data

Article detail can still load a skipped advertisement by direct `article_id` if an operator navigates there, but reader list surfaces should not offer it.

## Operator Visibility

Operator-facing article processing APIs should keep advertisement skips visible. The detail view should expose:

- `content_type`
- `classification_reason`
- latest enrichment status `skipped_advertisement`

This gives operators an audit trail and makes misclassification debuggable.

## Error Handling

- If classification says `advertisement`, missing translation text is valid.
- If classification says `article` or `uncertain`, missing translation text is invalid and should fail the enrichment attempt.
- If the advertisement output cannot be written, the enrichment run should fail normally.
- If article processing succeeds as an advertisement skip, it should not be eligible for automatic retry unless the source input changes or the operator requests manual retry.

## Testing Plan

Tests should cover:

- worker defaults use article concurrency 4 and batch size 8
- Compose passes article worker concurrency and poll settings to the worker
- empty queue processing does not create a `scheduler_run`
- non-empty queue processing still creates and finalizes a `scheduler_run`
- article batch size can exceed article concurrency without exceeding thread pool concurrency
- translator accepts `article`, `advertisement`, and `uncertain` response shapes
- advertisement classification skips summary/tagging
- advertisement skips mark article processing as succeeded
- latest usable enrichment lookup includes `skipped_advertisement` where operator views need it
- reader article lists exclude skipped advertisements
- document visible article lists exclude skipped advertisements
- operator article-processing detail includes content type and classification reason

## Rollout Notes

The first deployment should use:

- `ARTICLE_WORKER_CONCURRENCY=4`
- `ARTICLE_WORKER_BATCH_SIZE=8`
- `PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS=10`
- `PROCESSING_IDLE_POLL_INTERVAL_SECONDS=60`

If Gemini rate limits appear, reduce `ARTICLE_WORKER_CONCURRENCY` first. Batch size can stay higher than concurrency because it only controls how much work a pass selects, not simultaneous model calls.
