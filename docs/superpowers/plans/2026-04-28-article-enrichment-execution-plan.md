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

## Current Starting Point

The repository already provides:

- persisted `final_articles` with English title and body input
- persisted enrichment tables and validation-friendly schema
- repository helpers for creating and finalizing enrichment runs
- latest-visible enrichment version rules in storage logic
- a Gemini HTTP integration pattern through the continuation matcher
- CLI patterns for parse-time write paths and read-only inspection commands

The main missing pieces are:

- a Gemini client for article translation
- a Gemini client for summary and tag generation
- orchestration logic that executes both stages and persists results
- write and read CLI entrypoints for enrichment

## Recommended Delivery Order

### Slice 1: Read Path Foundations

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

### Slice 2: Gemini Translation Client

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

### Slice 3: Gemini Summary And Tag Client

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

### Slice 4: Enrichment Orchestration

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

### Slice 5: CLI Write Surface

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

### Slice 6: CLI Read Surface

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

## Suggested File-Level Delivery

### Likely production files

- [gemini.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/gemini.py)
- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
- `src/newspaper_translator/article_enrichment.py`
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)

### Likely test files

- [test_gemini.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_gemini.py)
- `tests/test_article_enrichment.py`
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

## Success Criteria

We should consider this plan successfully executed when the repository can:

- select one persisted `final_article`
- call Gemini twice using the project token
- persist translated title, translated body, summary, and ordered tags
- record correct `succeeded`, `partial`, and `failed` run history
- expose the latest visible enrichment result through CLI

## Recommended First Vertical Slice

The fastest reliable first slice is:

1. add a repository helper that loads one final article by `article_id`
2. implement the translation Gemini client
3. implement just enough orchestration to create a run and persist a successful translation-plus-summary-plus-tags result
4. expose it through `phase3-enrich-article`
5. then add `phase3-latest-enrichment`

This order gets one real end-to-end result into the database quickly while keeping the code easy to verify and expand later.
