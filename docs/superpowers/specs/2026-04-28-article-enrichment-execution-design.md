# Article Enrichment Execution Design

Date: 2026-04-28

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [MinerU Phase 3 Parsing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-mineru-phase-3-design.md)
- [Cross-Page Continuation Matching Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-27-cross-page-continuation-matching-design.md)
- [Article Persistence And Enrichment Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-persistence-and-enrichment-design.md)

## Overview

This document defines the first executable enrichment slice for persisted final articles.

The repository already has:

- persisted `final_articles` as the durable English source layer
- persisted `article_enrichment_runs`, `article_enrichment_outputs`, and `article_tags`
- latest-visible version rules for parse and enrichment history

The current gap is that no runtime path actually uses the configured Gemini token to generate:

- Chinese title translation
- Chinese body translation
- Chinese summary
- ordered article tags

This slice fills that gap with a two-stage Gemini enrichment workflow that is:

- article-centric
- asynchronous relative to parsing
- versioned through the existing enrichment tables
- strict about JSON shape and output validation

## Goals

- Use the project `GEMINI_TOKEN` to enrich one persisted final article
- Generate `translated_title_zh`, `translated_body_zh`, `summary_zh`, and `tags`
- Persist every enrichment attempt as a separate `article_enrichment_run`
- Support `succeeded`, `partial`, and `failed` outcomes through real execution logic
- Keep outputs structured and directly consumable by later CLI or dashboard surfaces
- Provide a minimal CLI write path and a minimal CLI read path for validation

## Non-Goals

- Running enrichment inside the parse transaction
- Building the dashboard or web article card surfaces in this slice
- Bulk scheduling or worker orchestration across many documents in this slice
- Adding semantic search, ranking, or recommendation logic
- Supporting multiple LLM providers in this first execution slice

## Recommended Approach

Use a two-stage Gemini workflow.

### Why Two Stages

The repository's persistence model already tracks translation, summary, and tagging as independently meaningful sub-results. A two-stage flow matches that model better than a single large call or four independent calls.

Recommended stages:

1. translation stage
   - generate `translated_title_zh`
   - generate `translated_body_zh`
2. summary and tagging stage
   - generate `summary_zh`
   - generate `tags`

Why this is the right trade-off:

- simpler than four independent calls
- safer than a single monolithic call
- preserves natural `partial` behavior
- keeps prompt and validation logic small enough to reason about

## High-Level Architecture

The slice should introduce four focused units.

### 1. `GeminiArticleTranslator`

Purpose:

- call Gemini once for Chinese title and body translation

Responsibilities:

- build the translation prompt from persisted English article input
- require strict JSON output
- parse and validate the returned JSON shape

Suggested output shape:

```json
{
  "translated_title_zh": "中文标题",
  "translated_body_zh": "中文正文"
}
```

### 2. `GeminiArticleSummarizerTagger`

Purpose:

- call Gemini once for Chinese summary and ordered tags

Responsibilities:

- build the summary and tag prompt using English source plus successful Chinese translation
- require strict JSON output
- parse and validate the returned JSON shape

Suggested output shape:

```json
{
  "summary_zh": "中文摘要",
  "tags": ["标签1", "标签2", "标签3"]
}
```

### 3. `article_enrichment.py`

Purpose:

- orchestrate a single article enrichment run from start to finish

Responsibilities:

- load the article source input
- derive stable `input_hash`
- create the enrichment run
- invoke translation first
- invoke summary and tagging only after translation succeeds
- validate each stage
- persist outputs and tags
- finalize run status as `succeeded`, `partial`, or `failed`

### 4. `manage.py` command surface

Purpose:

- expose a minimal operator-facing execution and inspection path

Recommended first commands:

- `phase3-enrich-article`
- `phase3-latest-enrichment`

## Data Flow

The execution flow should be:

1. load one `final_article` by `article_id`
2. create `article_enrichment_run(status='running')`
3. derive `input_hash` from stable English source input
4. call `GeminiArticleTranslator`
5. validate translation result
6. if translation succeeds, call `GeminiArticleSummarizerTagger`
7. validate summary and tag result
8. persist `article_enrichment_outputs`
9. persist ordered `article_tags`
10. finalize the run as:
    - `succeeded` when all sub-steps succeed
    - `partial` when translation succeeds but summary or tagging does not fully succeed
    - `failed` when no usable output exists

This flow intentionally does not mutate parse history or final article records.

## Prompt And JSON Contract

The Gemini prompts should be strict and minimal.

Shared hard rules:

- return JSON only
- do not use Markdown code fences
- do not include explanations
- do not include extra fields
- preserve article meaning rather than literal word order

### Translation Contract

Required fields:

- `translated_title_zh`
- `translated_body_zh`

Format rules:

- `translated_title_zh`
  - required
  - single-line string
  - no explanatory prefix
  - no quotation wrappers unless naturally part of the title
- `translated_body_zh`
  - required
  - may contain multiple paragraphs
  - should preserve article paragraph structure where practical
  - must not prepend commentary such as "以下是翻译"

### Summary And Tag Contract

Required fields:

- `summary_zh`
- `tags`

Format rules:

- `summary_zh`
  - required
  - single paragraph
  - no line breaks
  - target length approximately 60 to 140 Chinese characters
  - should read like a card summary, not a translation excerpt
- `tags`
  - required
  - 3 to 8 items
  - short Chinese phrases, not full sentences
  - no leading `#`
  - no duplicate tags
  - prioritize topic, region, industry, and event labels

## Validation Rules

Validation should stay deterministic and conservative.

### Translation Validation

The translation stage fails when:

- JSON cannot be parsed
- `translated_title_zh` is missing or empty
- `translated_body_zh` is missing or empty

### Summary Validation

The summary stage fails when:

- JSON cannot be parsed
- `summary_zh` is missing or empty

### Tag Validation

The tagging stage fails when:

- `tags` is not a list
- fewer than 3 tags remain after normalization
- more than 8 tags are returned
- all tags collapse to empty or duplicate values

### Allowed Normalization

Only minimal normalization should happen automatically:

- trim surrounding whitespace
- drop empty tag entries
- deduplicate tags while preserving first-seen order

Do not attempt fuzzy repair of malformed JSON or invented fields.

## Run Status Semantics

The enrichment run should use the following execution semantics.

### `failed`

Use `failed` when:

- translation fails entirely
- no usable enrichment output can be persisted

Behavior:

- do not run summary and tagging if translation failed
- preserve the failed run for history and debugging

### `partial`

Use `partial` when:

- translation succeeds
- but summary and tagging do not both succeed

Examples:

- translated title and body persist successfully, but summary generation fails
- translated title and body persist successfully, summary succeeds, but tag validation fails

### `succeeded`

Use `succeeded` when:

- translation succeeds
- summary succeeds
- tags succeed
- outputs and tags persist cleanly

## CLI Surface

This slice should expose only the smallest useful command set.

### `phase3-enrich-article`

Purpose:

- enrich one persisted final article

Suggested inputs:

- `--article-id`
- `--database-url`

Suggested output:

- JSON summary of the created enrichment run
- enough fields to verify outcome quickly, such as:
  - `enrichment_run_id`
  - `article_id`
  - `status`
  - `provider_name`
  - `model_name`

### `phase3-latest-enrichment`

Purpose:

- inspect the latest usable enrichment output for one article

Suggested inputs:

- `--article-id`
- `--database-url`

Suggested output:

- latest visible enrichment record
- translated title
- summary
- translated body
- ordered tags

## Error Handling

The slice should preserve history and avoid destructive overwrites.

Rules:

- every execution attempt creates a new run
- later failed runs do not hide older usable enrichment output
- transport errors, malformed JSON, and validation failures should be recorded on the run through `error_message`
- the orchestration layer should keep stage-specific reasoning local and persist only the resulting run state and outputs

## Testing Strategy

Implementation should follow strict TDD.

Recommended first test groups:

### 1. Gemini client contract tests

- translation client builds a strict JSON request
- translation client parses valid translation output
- summary and tag client builds a strict JSON request
- summary and tag client parses valid summary and tag output
- malformed Gemini JSON raises a repository-specific error

### 2. Enrichment orchestration tests

- a successful enrichment run writes outputs and tags and ends in `succeeded`
- translation success plus summary or tag failure ends in `partial`
- translation failure ends in `failed`
- `input_hash` is stable for identical article input

### 3. Validation tests

- empty translated title fails translation validation
- empty translated body fails translation validation
- empty summary fails summary validation
- tag counts outside `3..8` fail tagging validation
- duplicate and blank tags normalize correctly before final validation

### 4. CLI tests

- `phase3-enrich-article` invokes the orchestration entry
- `phase3-latest-enrichment` returns the latest visible record

## Rollout Boundary

This slice should stop after:

- enriching a single article on demand
- persisting the result correctly
- exposing the latest visible enrichment result through the CLI

The following should remain separate later slices:

- `phase3-enrich-document`
- scheduled or worker-driven enrichment
- dashboard cards and article detail pages
- multi-provider model support

## Success Criteria

This design should be considered successful when the repository can:

- take one persisted English article as input
- use the configured Gemini token to generate Chinese title, body, summary, and tags
- store every enrichment attempt in versioned history
- preserve usable outputs when a later run fails
- expose the latest visible enrichment result through a simple CLI read path

## Final Recommendation

Implement the first enrichment execution slice as a two-stage Gemini workflow.

Use:

- one translation call for `translated_title_zh` and `translated_body_zh`
- one summary and tagging call for `summary_zh` and `tags`

Persist everything through the existing enrichment tables and version rules.

This approach is the best fit for the repository's current architecture because it:

- matches the newly added persistence model
- supports clean `partial` semantics
- keeps prompts and tests manageable
- moves the project closer to the final bilingual article-reading experience without prematurely building dashboard or scheduling infrastructure
