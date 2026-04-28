# Article Enrichment Execution Plan

Date: 2026-04-28

Related documents:

- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)
- [Article Persistence And Enrichment Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-persistence-and-enrichment-design.md)
- [Newspaper Translator Progress Summary](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/status/2026-04-28-progress-summary.md)

## Goal

This plan turns the approved enrichment execution design into a staged build order that reaches one real, versioned Gemini enrichment run for one persisted final article.

The target outcome is:

- one CLI command that enriches one stored article with the project `GEMINI_TOKEN`
- versioned persistence for translated title, translated body, summary, and tags
- reliable `succeeded`, `partial`, and `failed` run semantics
- a minimal CLI read surface for the latest visible enrichment result

## Execution Status

Status on 2026-04-28: completed for the intended single-article execution slice.

Delivered implementation:

- repository read helpers for loading one `final_article` and one latest visible enrichment record
- `GeminiArticleTranslator` for strict-JSON title/body translation
- `GeminiArticleSummarizerTagger` for strict-JSON summary and ordered tags
- `article_enrichment.py` orchestration with `succeeded`, `partial`, and `failed` run semantics
- `phase3-enrich-article` CLI write path
- `phase3-latest-enrichment` CLI read path
- prompt version `article-enrichment-v2` with explicit newspaper-fragment and continuation-marker guidance

Validation notes:

- targeted TDD cycle completed for storage helpers, Gemini clients, orchestration, and CLI
- local test suite passed after implementation
- real PDF visual inspection and real Gemini runs confirmed the end-to-end path works on the local Wall Street Journal sample
- real validation showed that enrichment quality depends heavily on whether continuation fragments have been merged and on how much MinerU layout noise remains in the English source text

## Current Starting Point

The repository already provides:

- persisted `final_articles` with English title and body input
- persisted enrichment tables and validation-friendly schema
- repository helpers for creating and finalizing enrichment runs
- latest-visible enrichment version rules in storage logic
- a Gemini HTTP integration pattern through the continuation matcher
- CLI patterns for parse-time write paths and read-only inspection commands

The original gaps listed in this plan have now been filled for the single-article execution slice.

## Recommended Delivery Order

### Slice 1: Read Path Foundations

Status: completed

Add the missing article-centric repository helpers needed by the enrichment pipeline.

Scope:

- load one `final_article` by `article_id`
- expose latest visible enrichment by `article_id`
- if needed, add enrichment run history reads for debugging

Why first:

- the orchestration layer should not know raw SQL details
- this keeps later implementation focused on behavior rather than database access

Exit criteria:

- one persisted final article can be loaded as a stable enrichment input object
- latest visible enrichment remains queryable by article id
- completed through `get_final_article(...)` and `get_latest_article_enrichment(...)`

### Slice 2: Gemini Translation Client

Status: completed

Implement a dedicated translation client that only returns:

- `translated_title_zh`
- `translated_body_zh`

Scope:

- prompt builder
- strict JSON contract
- HTTP request through the existing Gemini transport pattern
- response parsing
- translation output validation

Why second:

- translation is the hard dependency for the second enrichment stage
- this keeps the first executable Gemini slice narrow and easy to debug

Exit criteria:

- one English article input produces a parsed translation result object
- malformed JSON or missing required fields fail deterministically
- completed through `GeminiArticleTranslator`

### Slice 3: Gemini Summary And Tag Client

Status: completed

Implement a second dedicated Gemini client that returns:

- `summary_zh`
- `tags`

Scope:

- summary and tag prompt builder
- strict JSON contract
- response parsing
- summary and tag validation
- minimal normalization for whitespace and duplicate tags

Why third:

- this client depends on the output conventions from the translation stage
- it should remain independently testable and replaceable

Exit criteria:

- one article plus successful translation can produce a valid summary and ordered tags
- invalid tag counts or empty summary values fail deterministically
- completed through `GeminiArticleSummarizerTagger`

### Slice 4: Enrichment Orchestration

Status: completed

Implement the main enrichment execution service in a focused module such as `article_enrichment.py`.

Scope:

- compute stable `input_hash`
- create `article_enrichment_run(status='running')`
- call translation stage
- conditionally call summary and tag stage
- persist outputs and tags
- finalize run status correctly
- attach useful `error_message` values on failure

Why fourth:

- the orchestration layer should be the first place where status semantics come together
- keeping it separate from Gemini clients avoids tangled prompt and persistence logic

Exit criteria:

- successful two-stage execution persists outputs and tags and ends in `succeeded`
- translation success plus later failure ends in `partial`
- translation failure ends in `failed`
- completed through `enrich_article(...)`

### Slice 5: CLI Write Surface

Status: completed

Add a narrow execution command:

- `phase3-enrich-article --article-id ... --database-url ...`

Scope:

- configuration loading from environment
- Gemini client construction
- orchestration call
- JSON result output

Why fifth:

- the orchestration service should already be proven before exposing it through CLI
- this keeps CLI work mostly mechanical and low risk

Exit criteria:

- the command can enrich one persisted article end to end
- output includes the created run id and final status
- completed through `phase3-enrich-article`

### Slice 6: CLI Read Surface

Status: completed

Add a minimal inspection command:

- `phase3-latest-enrichment --article-id ... --database-url ...`

Scope:

- fetch latest visible enrichment
- output translated title, translated body, summary, and ordered tags

Why sixth:

- this proves the version rule and read path after the write path exists
- it gives a practical operator-facing validation surface before any dashboard work

Exit criteria:

- one successfully enriched article can be inspected through CLI
- later failed runs do not hide older usable output
- completed through `phase3-latest-enrichment`

## Execution Notes

What worked well:

- the two-stage Gemini split aligned cleanly with the persistence model and made `partial` semantics straightforward
- strict JSON contracts kept parsing and validation logic small and testable
- TDD kept the slice focused and avoided mixing transport, orchestration, and CLI concerns

What was learned during real validation:

- MinerU output can still contain broken words, glued continuation markers, and occasional stray tokens
- if continuation matching does not run, Gemini can produce fluent Chinese from an incomplete fragment, which risks hiding upstream article-boundary problems
- the `article-enrichment-v2` prompt improves behavior by warning Gemini about newspaper continuation fragments and asking it to preserve jump markers, but current output still translates some markers rather than preserving the exact English source string

## TDD Queue

Each slice should follow the strict loop:

1. write one failing test
2. run the narrowest possible target and verify RED
3. add the minimum code to reach GREEN
4. rerun the targeted test
5. refactor while staying green

Recommended first tests in order:

1. `loads one final article by article id for enrichment input`
2. `translation client builds strict Gemini JSON request`
3. `translation client parses translated title and body`
4. `translation client rejects malformed JSON payload`
5. `summary and tag client builds strict Gemini JSON request`
6. `summary and tag client parses summary and ordered tags`
7. `summary and tag client rejects invalid tag counts`
8. `enrichment orchestration persists a succeeded run`
9. `enrichment orchestration marks translation-only success as partial when stage two fails`
10. `enrichment orchestration marks translation failure as failed`
11. `phase3-enrich-article calls orchestration and returns run JSON`
12. `phase3-latest-enrichment returns the latest visible enrichment record`

Implemented additional tests beyond the original queue:

- translation prompt includes newspaper-fragment and jump-marker guidance
- summary payload rejects line breaks
- orchestration persists `partial` when stage two fails
- orchestration persists `failed` when translation fails

## Suggested File-Level Delivery

### Likely production files

- [gemini.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/gemini.py)
- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
- [article_enrichment.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_enrichment.py)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)

### Likely test files

- [test_gemini.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_gemini.py)
- [test_article_enrichment.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_article_enrichment.py)
- [test_manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_manage.py)
- possibly [test_article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_article_store.py) for read helper additions

## Risks To Watch

- letting the Gemini clients return loosely structured text and pushing cleanup into orchestration
- coupling CLI parsing too tightly to enrichment logic instead of using a dedicated service module
- treating every non-perfect run as `failed` and losing the value of `partial`
- silently mutating malformed tags or summaries instead of failing validation clearly
- expanding this slice into batch orchestration or dashboard work before the single-article path is stable

## What We Are Not Doing Yet

- `phase3-enrich-document`
- scheduled enrichment retries
- worker-based background execution
- dashboard article cards or detail pages
- non-Gemini providers
- prompt optimization for style beyond the first strict-output baseline
- systematic cleanup of MinerU newspaper-layout artifacts before enrichment
- hard guarantees that continuation markers stay verbatim in the translated output

## Success Criteria

We should consider this plan successfully executed when the repository can:

- select one persisted `final_article`
- call Gemini twice using the project token
- persist translated title, translated body, summary, and ordered tags
- record correct `succeeded`, `partial`, and `failed` run history
- expose the latest visible enrichment result through CLI

Result: achieved for the single-article execution slice.

## Recommended Next Vertical Slice

The next highest-value slice should focus on enrichment input quality and continuation safety:

1. normalize MinerU newspaper artifacts before enrichment
2. detect and preserve continuation markers in a deterministic pre-enrichment step
3. define when markers should remain verbatim English versus when a structured placeholder should be used
4. add tests using real noisy examples such as `PleaseturntopageA7`, broken hyphenation, and stray OCR tokens
5. only after that, expand from single-article enrichment to document-level and worker-level execution

This order hardens correctness before adding scale.
