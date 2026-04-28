# Article Persistence And Enrichment Design

Date: 2026-04-28

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [Newspaper Translator Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-04-22-newspaper-translator-implementation-plan.md)
- [MinerU Phase 3 Parsing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-mineru-phase-3-design.md)
- [Cross-Page Continuation Matching Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-27-cross-page-continuation-matching-design.md)

## Overview

This document defines how the repository should persist parsed newspaper articles and later article-level AI enrichment results.

The design extends the current Phase 3 parsing path from transient CLI JSON output into durable storage centered on:

- parse-run history for one raw PDF across repeated parsing attempts
- fragment-level and continuation-match-level debug visibility
- final article records that default to the latest successful parse result for a document
- enrichment-run history for tags, Chinese summaries, Chinese titles, and full Chinese translations

The persistence model must support the current operating mode:

- local single-machine batch processing
- Docker container deployment
- SQLite as the runtime database
- later asynchronous enrichment after parsing succeeds

## Goals

- Persist every parse attempt for a raw PDF without overwriting older history
- Preserve enough intermediate parsing state to explain why a final article looks the way it does
- Make the default read path article-centric and current-version-centric
- Persist article publication date as a first-class field
- Persist tags, Chinese summaries, Chinese titles, and Chinese full translations
- Preserve history for every enrichment attempt without overwriting older results
- Keep parsing persistence and enrichment persistence cleanly separated
- Keep the design simple enough for SQLite and single-machine Docker execution

## Non-Goals

- Introducing PostgreSQL in this slice
- Building dashboard routes or UI in this slice
- Performing enrichment synchronously inside the parsing transaction
- Designing full-text search or semantic search
- Defining the final prompt contents for tags, summary, or translation generation

## Database Choice

This slice should continue to use SQLite as the primary database.

Why SQLite is the right choice here:

- the repository already uses SQLite migrations and `sqlite:///` runtime settings
- the target operating mode is local single-machine batch processing, not multi-instance online serving
- Dockerized local use with a mounted data volume matches SQLite well
- copying, inspecting, and backing up one database file is simple during early development

PostgreSQL should remain a possible later migration path if the project evolves into a multi-worker or multi-user service, but it is unnecessary complexity for the current workload.

## Design Principles

- Store one authoritative structured result in the database rather than maintaining a second long-term JSON artifact store for repository-native outputs
- Treat parsing and enrichment as separate versioned workflows
- Preserve failed and partial runs for observability
- Never let a newly failed run overwrite an older successful current version
- Default queries should answer "what is the latest usable article version?" without hiding history
- Intermediate records should make it possible to trace final output back to its source fragments and model runs

## Current Starting Point

The repository already provides:

- durable raw PDF storage in `documents`
- repeatable MinerU parsing to `full.md`
- Markdown-to-fragment and fragment-to-final-article reconstruction
- optional Gemini continuation matching
- CLI JSON output for final articles

The current gap is persistence for:

- parse run history
- parsed fragments
- continuation matches
- final article outputs
- article enrichment outputs and their version history

## High-Level Persistence Architecture

The persistence model should have two durable layers.

### 1. Parsing Persistence Layer

This layer owns:

- one parse run per parse attempt
- raw parsed fragments for that attempt
- continuation-match records for that attempt
- final article records for that attempt

### 2. Enrichment Persistence Layer

This layer owns:

- one enrichment run per enrichment attempt for one final article
- the latest and historical tag outputs
- the latest and historical Chinese summary outputs
- the latest and historical Chinese title outputs
- the latest and historical Chinese full translation outputs

These two layers are connected through final articles, but they must remain independently retryable and independently queryable.

## Publication Date

Publication date is required article metadata and must be stored durably.

The field should be named `publication_date` and normalized as `YYYY-MM-DD`.

Extraction priority should be:

1. Parse from the PDF filename
2. If the filename does not contain a valid date, derive it from parseable document text or Markdown content
3. If no date can be resolved, mark the parse run as failed instead of creating undated final articles

This field should be stored in:

- `parse_runs`, because the entire parse attempt belongs to one newspaper issue date
- `final_articles`, because the dashboard and article queries should be able to filter by date directly

## Parsing Data Model

### `parse_runs`

Represents one parsing attempt for one imported raw document.

Suggested fields:

- `parse_run_id`
- `document_key`
- `status`
- `parser_name`
- `parser_version`
- `publication_date`
- `continuation_matcher_name`
- `continuation_matcher_version`
- `mineru_batch_id`
- `mineru_file_id`
- `markdown_path`
- `started_at`
- `finished_at`
- `error_message`

Rules:

- `status` should support `running`, `succeeded`, and `failed`
- one document may have many parse runs
- failed parse runs remain queryable and do not delete their partial artifacts

### `article_fragments`

Represents the raw fragment objects extracted from one parse run before final article merge decisions.

Suggested fields:

- `fragment_id`
- `parse_run_id`
- `source_order`
- `title`
- `body_text`
- `continued_to_page`
- `continued_from_page`
- `is_continuation_candidate`
- `created_at`

Rules:

- this table stores parser-native fragment outputs, not dashboard-ready articles
- fragments remain even if later matching fails

### `continuation_matches`

Represents continuation-pair decisions for one parse run.

Suggested fields:

- `match_id`
- `parse_run_id`
- `front_fragment_id`
- `back_fragment_id`
- `matcher_name`
- `matcher_raw_response`
- `decision_status`
- `decision_reason`
- `created_at`

Rules:

- `decision_status` should support `accepted`, `ignored`, and `invalid`
- malformed or impossible matcher output should be recorded as ignored or invalid rather than silently disappearing

### `final_articles`

Represents the final reconstructed article set for one parse run.

Suggested fields:

- `article_id`
- `parse_run_id`
- `document_key`
- `publication_date`
- `article_order`
- `primary_source_order`
- `source_fragment_count`
- `title_en`
- `body_text_en`
- `created_at`

Rules:

- one parse run can create many final articles
- final articles are immutable results of one parse run
- English source content should be stored here because enrichment derives from it

### `final_article_fragments`

Represents lineage between one final article and its source fragments.

Suggested fields:

- `article_id`
- `fragment_id`
- `fragment_role`
- `sequence_index`

Rules:

- `fragment_role` should support `standalone`, `front`, and `back`
- this table is required for tracing one final article back to its fragment inputs

## Current Final Article Version Rule

The default final version for one raw document should be defined as:

- the latest `parse_run` for that `document_key`
- where `parse_runs.status = succeeded`
- ordered by `finished_at DESC`

The `final_articles` belonging to that parse run are the current article set for that document.

This rule means:

- repeated successful reparses can replace the default visible version
- failed later runs do not remove a previously successful visible version
- history remains available for comparison and debugging

## Enrichment Data Model

Enrichment must preserve history independently from parsing history.

One final article may have many enrichment runs over time because models, prompts, or validation rules may change.

### `article_enrichment_runs`

Represents one enrichment attempt for one final article.

Suggested fields:

- `enrichment_run_id`
- `article_id`
- `parse_run_id`
- `status`
- `provider_name`
- `model_name`
- `prompt_version`
- `input_hash`
- `started_at`
- `finished_at`
- `error_message`

Rules:

- `status` should support `running`, `partial`, `succeeded`, and `failed`
- `input_hash` should be derived from stable English source input such as title and body text
- one article may have many enrichment runs

### `article_enrichment_outputs`

Represents structured outputs for one enrichment run.

Suggested fields:

- `enrichment_run_id`
- `translated_title_zh`
- `summary_zh`
- `translated_body_zh`
- `translation_status`
- `summary_status`
- `tagging_status`
- `created_at`

Rules:

- translation, summary, and tagging status should be tracked independently
- one successful sub-step should not be erased by another failed sub-step
- Chinese title and Chinese body translation should be stored separately
- Chinese summary should be stored separately from translated body text because it serves a distinct card-display use case

### `article_tags`

Represents tag outputs for one enrichment run.

Suggested fields:

- `article_tag_id`
- `enrichment_run_id`
- `tag_text`
- `tag_order`

Rules:

- a valid successful tagging result should produce 3 to 8 tags
- tags belong to one enrichment run, not directly to the article root record

## Current Enrichment Version Rule

The default visible enrichment version for one article should be defined as:

- the latest `article_enrichment_run` for that `article_id`
- where `status in ('partial', 'succeeded')`
- ordered by `finished_at DESC`

Why `partial` is acceptable for the default visible layer:

- parsing should not wait for enrichment
- enrichment is explicitly asynchronous
- a card may still be useful when summary and tags exist but full translation is missing

This rule allows:

- card views to show the latest usable Chinese title, summary, and tags
- detail views to show the latest usable Chinese full translation when present
- failed later enrichment runs to leave an older usable result in place

## Write Flow

### Parsing Flow

1. Create a `parse_run` in `running`
2. Resolve and validate `publication_date`
3. Run MinerU and persist `mineru_batch_id`, `mineru_file_id`, and `markdown_path`
4. Extract and persist `article_fragments`
5. Execute continuation matching when configured and persist `continuation_matches`
6. Build and persist `final_articles`
7. Persist `final_article_fragments`
8. Mark the `parse_run` as `succeeded` and set `finished_at`

Failure behavior:

- if publication date cannot be resolved, fail the parse run
- if the matcher fails, keep the parse run alive and persist unmatched final articles
- if parsing fails after some intermediate writes, keep the run and persisted intermediate data, then mark the run as `failed`

### Enrichment Flow

1. Create an `article_enrichment_run` in `running`
2. Generate tags, summary, Chinese title, and Chinese body translation as separate sub-steps
3. Validate each sub-step independently
4. Persist `article_enrichment_outputs`
5. Persist `article_tags`
6. Mark the enrichment run as:
   - `succeeded` when all required sub-steps succeed
   - `partial` when at least one useful sub-step succeeded but not all required sub-steps succeeded
   - `failed` when no usable output exists

This keeps retries targeted and prevents one failed translation from discarding already successful tags or summary output.

## Query Surfaces

The default query experience should be final-article-centric rather than parse-run-centric.

Recommended initial query surfaces:

- latest final articles for one document
- parse run history for one document
- fragment list for one parse run
- continuation matches for one parse run
- final articles for one parse run
- latest visible enrichment for one article
- enrichment run history for one article

This keeps ordinary browsing simple while preserving deep inspection paths for debugging.

## Idempotency And History Rules

- Every parse attempt creates a new `parse_run`
- Every enrichment attempt creates a new `article_enrichment_run`
- New failed runs do not overwrite earlier successful current versions
- Repeated runs on the same input may share the same `input_hash`, but they still remain distinct historical runs
- Repository-native parsing and enrichment outputs should live in the database as the durable source of truth

## Validation Rules

### Parse Validation

- `publication_date` must exist before a parse run can succeed
- `final_articles` must not exist without a parent `parse_run`
- `final_article_fragments` must refer only to fragments from the same parse run

### Enrichment Validation

- successful tagging must produce between 3 and 8 tags
- successful summary output must produce non-empty `summary_zh`
- successful translation output must produce non-empty `translated_title_zh` and `translated_body_zh`

## Indexing Guidance

SQLite indexes should prioritize the main read paths.

Recommended early indexes:

- `parse_runs(document_key, status, finished_at)`
- `final_articles(parse_run_id, article_order)`
- `final_articles(publication_date, article_order)`
- `article_fragments(parse_run_id, source_order)`
- `continuation_matches(parse_run_id, decision_status)`
- `article_enrichment_runs(article_id, status, finished_at)`
- `article_tags(enrichment_run_id, tag_order)`
- `article_tags(tag_text)`

## Migration Strategy

This slice should be introduced through additive SQLite migrations.

Recommended migration order:

1. add parsing persistence tables
2. add enrichment persistence tables
3. add indexes for current-version query paths

This preserves compatibility with the current repository while allowing incremental tests and rollout.

## Testing Strategy

The persistence design should be implemented with strict TDD.

Recommended test groups:

1. parse run persistence
   - one parse run persists fragments, matches, and final articles
   - repeated parses for one document preserve history
   - latest successful parse run is selected as the default visible article set
2. enrichment persistence
   - one enrichment run persists Chinese title, summary, translation, and tags
   - tag count validation enforces the 3 to 8 range
   - partial enrichment keeps successful outputs
3. current-version queries
   - failed later parse runs do not hide older successful parse output
   - failed later enrichment runs do not hide older usable enrichment output
4. lineage and debugging
   - one final article can be traced back to its source fragments
   - one visible enrichment output can be traced back to its enrichment run metadata

## Success Criteria

This design should be considered successful when the repository can:

- persist every parse attempt for one raw PDF
- retain fragment and continuation-match debug history
- return the latest successful final article set for one document
- persist publication date on parse runs and final articles
- persist tags, Chinese summary, Chinese title, and Chinese full translation for articles
- retain enrichment history across repeated runs
- return the latest usable enrichment version for article display without deleting historical runs

## Final Recommendation

Implement article persistence and enrichment persistence as two versioned SQLite-backed layers.

The parsing layer should use:

- `parse_runs`
- `article_fragments`
- `continuation_matches`
- `final_articles`
- `final_article_fragments`

The enrichment layer should use:

- `article_enrichment_runs`
- `article_enrichment_outputs`
- `article_tags`

The system should default to:

- latest successful parse run per document
- latest usable enrichment run per article

This approach matches the current local Dockerized batch-processing workflow, preserves observability, supports future dashboard queries, and stays aligned with the original project goal of durable article-level tags, summaries, and translations.
