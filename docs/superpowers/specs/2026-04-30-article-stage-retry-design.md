# Article Stage Retry And Identity Design

Date: 2026-04-30

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [Article Persistence And Enrichment Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-persistence-and-enrichment-design.md)
- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)
- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)
- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)

## Overview

This document redesigns retry behavior for article processing after the first end-to-end document pipeline has already been proven.

The current workflow treats document enrichment as one document-level step:

- `process_document()` persists the parsed articles for one document
- it then loops over every latest article in that document and calls `enrich_article()`
- if any article is not `succeeded`, the whole document is marked `failed_retryable`
- the next document-level scheduler pass re-runs document enrichment for all articles in the document

That behavior is too coarse for the current product.

Once MinerU has successfully produced markdown and the repository has persisted the parse result, the document-level parse work should be considered complete. A later article enrichment failure should not force the system back into a document-level retry path.

This design introduces:

- explicit stage boundaries between document parsing and article enrichment
- durable article identity across repeated parses of the same source file
- article-level retry queues for enrichment
- automatic deduplication so successful unchanged articles are not enriched again
- frontend-visible source metadata so operators and readers can see the originating file and page numbers for each article

## Goals

- Stop treating one article enrichment failure as a document-level retry condition
- Preserve document success once `parse_persist` has completed successfully
- Retry only the failed stage
- Make article enrichment retry independently schedulable and independently observable
- Reuse successful enrichment results when the article source input has not changed
- Re-enrich only the changed article when the same logical article is parsed again with different content
- Expose article source filename and page numbers in product-facing UI surfaces
- Keep the first slice at three stages:
  - `import/raw_pdf`
  - `parse_persist`
  - `article_enrich`

## Non-Goals

- Splitting article enrichment into `translate` and `summary_tag` in this slice
- Cross-document article identity matching across different source files or publication dates
- Replacing the current parse result schema with a fully versioned editorial model
- Building fuzzy identity matching across unrelated newspapers
- Adding user notifications or alerting workflows

## Product Decisions

The user-validated decisions for this slice are:

- stage granularity is currently three stages, with room to split `article_enrich` later
- article enrichment should support both automatic retry and manual retry
- automatic retry count stays aligned with current behavior and is capped at two retries after the initial attempt
- successful unchanged article enrichment should not be automatically scheduled again
- successful articles may be reprocessed only when:
  - the article source input changed for the same logical article
  - the operator explicitly forces a manual re-run

## Why The Current Model Is Wrong

The current document-level enrichment loop creates two problems.

### 1. Wrong Retry Boundary

`parse_persist` and `article_enrich` are operationally different stages.

If MinerU has already returned markdown and the parse result has been persisted, the document pipeline has already crossed the expensive and stateful boundary. A later summarization or translation failure does not invalidate the parse result and should not require the document to re-enter document-level retry.

### 2. Missing Deduplication

`article_enrichment_runs` already stores `input_hash`, provider, model, prompt version, and status history. But current scheduling ignores that history and re-runs the document's entire article set during the next document enrichment pass.

This causes:

- repeated enrichment work for already successful unchanged articles
- avoidable cost and latency
- noisy run history
- a mismatch between durable storage and runtime scheduling behavior

## Recommended Approach

Use a two-layer workflow:

1. document stages
   - own file import and parse persistence
2. article stages
   - own article enrichment retries and visibility

This is the recommended approach because it matches how the pipeline actually behaves:

- the PDF source file is the durable root artifact
- MinerU parse success is the document boundary
- enrichment is inherently article-centric and can fail partially

## Stage Model

The first stable stage model should be:

### 1. `import/raw_pdf`

Meaning:

- the source PDF was imported, deduplicated at the document layer, and stored locally

Owner:

- import audit and document ingestion flow

### 2. `parse_persist`

Meaning:

- MinerU successfully produced markdown
- the parse result was persisted into parse runs, fragments, continuation matches, and final articles

Owner:

- document processing flow

Success rule:

- if markdown is returned and the parse result is durably stored, the document has completed this stage

### 3. `article_enrich`

Meaning:

- each logical article has an independently schedulable enrichment lifecycle

Owner:

- article-level processing flow

Important rule:

- failure in `article_enrich` must not move the document back to `failed_retryable`

## Article Identity

The design requires a stable article identity that survives repeated parses of the same source file.

### Why `article_id` Is Not Enough

The current `final_articles.article_id` represents one persisted article row from one parse run. It is a version-specific identifier, not a stable logical article identifier.

When content changes because of:

- improved page splitting
- better continuation matching
- OCR cleanup
- small title or body corrections

the system still needs to know whether the new row is the same logical article.

### Stable Identity Rule

Introduce a durable `article_key` that represents one logical article within one source document lineage.

`article_key` should be assigned during `parse_persist` after the new final articles are known.

### Match Scope

Identity matching is limited to repeated parses of the same source document lineage.

This design does not attempt to match across different original files.

### Match Inputs

A new parsed article should attempt to match a historical logical article when:

- it comes from the same original file
- it shares at least one source page with a historical article candidate
- its normalized title or normalized body opening has at least 90 percent similarity with that candidate

### Normalization Rules

For the first slice, normalization should include:

- lowercasing
- removing whitespace

This follows the user-provided rule and keeps the first implementation intentionally narrow.

### Similarity Inputs

The two text candidates should be:

- normalized title
- normalized article opening

`article opening` means the leading excerpt of English body text used only for identity matching. The exact cutoff can be implementation-defined, but it must be stable and documented in code comments or tests.

### Match Outcome

- if a candidate matches, the new parsed row inherits that candidate's `article_key`
- otherwise a new `article_key` is created

## Source Metadata Model

The identity rule depends on durable source location data, so page metadata must become first-class persisted state.

### Required Source Metadata

Each final article must expose:

- original filename
- source page numbers

The page list should represent all pages contributing source fragments to the article, not only the first page.

### Persistence Direction

The repository already has fragment-level and final-article-fragment-level persistence. This slice should extend that model so each article can be queried with a stable page list.

Recommended persisted concepts:

- fragment page number
- article-to-page mapping or a queryable derivation from final article fragments

The implementation may choose whether the page list is:

- materialized in a dedicated relation
- or query-derived from persisted fragment rows

The important requirement is that page numbers are durable, queryable, and cheap enough for list/detail API surfaces.

## Enrichment Scheduling Model

Article enrichment should become an article-level processing concern rather than a document-level loop outcome.

### Current Problem

Today `document_processing.enrich_document_articles()` immediately executes enrichment for every latest article in the document and raises if any article is not `succeeded`.

That means:

- one failed article fails the document
- all articles are retried together later

### New Responsibility Split

After `parse_persist` succeeds:

- document processing should identify or create `article_key` values
- it should enqueue or refresh article enrichment work items
- it should not require every article to enrich successfully before the document can be considered successful at the document stage

### Article Processing Queue

Introduce an article-level processing state store, recommended as `article_processing_runs`.

Suggested fields:

- `article_key`
- `article_id`
  - points to the current parsed version that should be enriched
- `status`
  - `pending`
  - `running`
  - `succeeded`
  - `failed_retryable`
  - `failed_terminal`
  - `manual_retry_requested`
- `current_step`
  - initially only `enrich`
- `automatic_failure_count`
- `last_error_message`
- `last_success_input_hash`
- `last_attempt_started_at`
- `last_attempt_finished_at`
- `locked_by`
- `lock_expires_at`
- timestamps

This mirrors the repository's current document-processing style while leaving room for later sub-steps such as `translate` and `summary_tag`.

## Deduplication Rules

The system needs two kinds of deduplication.

### 1. Scheduling Deduplication

When a parsed article version becomes current for one `article_key`:

- if there is no successful enrichment result for that article version, enqueue enrichment
- if there is a successful result whose `input_hash` matches the current source input, do not enqueue enrichment
- if the same logical article now has a new current version with a different `input_hash`, enqueue enrichment only for that logical article

This is the primary fix for the current over-retry problem.

### 2. Run Creation Deduplication

Even if scheduling accidentally reaches an already-successful article, the runtime should still avoid writing duplicate enrichment runs when a matching successful result already exists for the same:

- logical article current version
- `input_hash`
- provider
- model
- prompt version

The runtime may implement this either by:

- checking before creating a new run
- or creating a cheap idempotency guard in the enrichment store layer

Either way, the observable behavior must be that automatic retries do not create duplicate successful histories for unchanged input.

## Retry Semantics

### Automatic Retry

Automatic article enrichment retry should follow the current system expectation:

- initial attempt
- up to 2 automatic retries after failure

If all attempts are exhausted:

- the article processing run becomes `failed_terminal`

### Manual Retry

Operators must be able to request retry for one logical article without affecting the whole document.

Manual retry should:

- reset the article processing status to `manual_retry_requested`
- preserve prior history
- allow a later scheduler tick or direct operator action to process the retry

### Document Retry Separation

Document manual retry remains useful for document-stage failures such as parse persistence issues.

But it should not be the primary remediation path for article enrichment failures once this design is implemented.

## Scheduler Behavior

The scheduler should evolve from document-only orchestration into mixed orchestration.

### Recommended Behavior

Each scheduler tick should be able to process both:

- eligible document work
- eligible article enrichment work

The implementation may process them:

- sequentially in one tick
- or through independent worker loops that share the same scheduler cadence

Either approach is acceptable for this slice as long as article enrichment no longer depends on a document re-run.

### Recommended Priority Rules

For article enrichment queue selection:

- `manual_retry_requested`
- `pending`
- `failed_retryable`

This follows the same operator-first pattern already used in document processing.

### Locking

Article processing should use the same lock pattern as document processing:

- claim before work
- set lock expiration
- release on success or failure
- recover stale `running` entries through timeout-based recovery

## Runtime Flow

The new high-level flow should be:

1. import and persist the raw document
2. run `parse_persist`
3. persist fragments, pages, final articles, and article identity mappings
4. finalize document processing as successful for the parse stage
5. create or refresh article enrichment queue items
6. scheduler claims article enrichment work
7. runtime checks for unchanged successful input
8. if unchanged successful input already exists, mark article processing as satisfied without a new run
9. otherwise execute `enrich_article()`
10. persist new enrichment outputs and update article processing state

## Frontend And API Changes

The user requested that the product surface show article file origin and page numbers.

### Article List And Detail Surfaces

Article-facing views should expose:

- source filename
- source page numbers

These fields should be visible at least in:

- article detail page
- article cards or article metadata surfaces where space allows

### Operator Surfaces

Operator views should expose article-level enrichment exceptions separately from document-level exceptions.

Recommended additions:

- article enrichment failure list
- manual single-article retry action
- visibility into source filename and page numbers for faster debugging

### Query Layer

The API query layer should provide UI-ready source metadata fields instead of forcing the frontend to reconstruct them.

Recommended article view model additions:

- `source_filename`
- `source_page_numbers`
- `article_processing_status`
- `article_processing_error`

## Data Model Direction

This design intentionally separates:

- logical article identity
- parsed article version
- enrichment attempt history
- article-stage processing state

Recommended persistence additions are:

### Required

- durable source page number persistence
- durable `article_key` persistence
- durable article-stage processing persistence

### Recommended But Flexible

- whether `article_key` lives directly on `final_articles` or through a separate identity table
- whether article pages are materialized or query-derived

The implementation plan should choose the smallest schema that still keeps these boundaries explicit.

## Migration Expectations

This slice will require schema migration.

Expected migration areas:

- add page metadata to persisted fragment or final article source structures
- add stable logical article identity persistence
- add article-stage processing persistence
- add indexes supporting:
  - article identity lookup by source file and page
  - article processing queue scans by status
  - latest successful enrichment lookup by `article_key` or current article version

## Testing Strategy

The implementation plan should include tests for the following behaviors.

### Identity Matching

- same original file, same page overlap, and title similarity over threshold inherit the same `article_key`
- same original file, same page overlap, and body opening similarity over threshold inherit the same `article_key`
- articles without qualifying similarity do not inherit the same `article_key`

### Source Metadata

- final article queries expose original filename
- final article queries expose all contributing page numbers
- cross-page merged articles show multiple source pages

### Scheduling And Deduplication

- unchanged already-successful articles are not re-enqueued
- if a logical article's input changes, only that logical article is enqueued
- duplicate successful enrichment run creation is prevented for unchanged input

### Failure Isolation

- one article enrichment failure does not mark the document as `failed_retryable`
- document status remains successful after parse persistence completes
- article processing transitions independently through retryable and terminal failure states

### Retry

- automatic retry stops after two retries
- manual single-article retry returns the item to an eligible state
- stale running article tasks recover safely

### Frontend And API

- article view models include source filename and page list
- operator queries distinguish document-stage and article-stage exceptions

## Recommended Implementation Order

1. persist page metadata needed for article source location
2. introduce stable logical article identity assignment
3. introduce article-stage processing persistence and queue logic
4. decouple document success from article enrichment success
5. add deduplication checks for unchanged successful input
6. add manual article retry endpoints and CLI
7. expose source filename and page numbers in article-facing and operator-facing APIs
8. update frontend views to display source metadata and article-stage exceptions

## Risks And Trade-Offs

### 1. False Positive Identity Matches

Two unrelated short articles on the same page may look similar after aggressive normalization.

Mitigation:

- require page overlap and high similarity threshold
- test with same-page multi-article cases
- keep the first rule intentionally narrow rather than broadly fuzzy

### 2. False Negative Identity Matches

If title cleanup changes heavily, the same logical article might get a new `article_key`.

Mitigation:

- allow either title similarity or body opening similarity
- keep manual re-run available
- structure the schema so matching heuristics can evolve later without reworking stage boundaries

### 3. Mixed Granularity During Transition

During migration, the system may temporarily have document-level exception views and article-level exception views at the same time.

Mitigation:

- explicitly scope document exceptions to document stages
- explicitly scope article exceptions to article enrichment

## Open Design Constraint For Later Work

Future slices may split `article_enrich` into smaller sub-steps such as:

- `translate`
- `summary_tag`

This design does not implement that split now, but it keeps the state model ready for it through `current_step` and independent article-stage persistence.

## Summary

The correct retry boundary for this product is no longer the whole document after parse persistence succeeds.

The system should:

- treat parse success as durable document-stage completion
- identify logical articles across repeated parses of the same source file
- persist source page metadata
- retry enrichment at article granularity
- skip unchanged already-successful articles
- expose source filename and page numbers in the frontend

This design solves the current retry inefficiency without overcommitting to a more granular AI sub-step model before the product actually needs it.
