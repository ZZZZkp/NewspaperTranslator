# Newspaper Translator TDD Test Plan

Date: 2026-04-22

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [Newspaper Translator Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-04-22-newspaper-translator-implementation-plan.md)

## Purpose

This document defines what we should test first, in what order, and at what scope before writing production code.

It follows the `superpowers:test-driven-development` rule:

`no production code without a failing test first`

The goal is not just to list test categories. The goal is to define a concrete TDD sequence for the first implementation phases so we can build the system with confidence and without slipping into tests-after.

## TDD Ground Rules For This Project

Before any production code is written for a behavior:

1. Write one failing test for one behavior.
2. Run only that test and confirm it fails for the expected reason.
3. Write the minimum code to make it pass.
4. Re-run the test and confirm it passes cleanly.
5. Refactor only while staying green.

Additional rules for this project:

- Prefer real value objects, real parsers, real database access, and real serialization logic in tests.
- Use fakes only at hard external boundaries such as Gmail, cloud model APIs, and OCR providers.
- Avoid tests that only assert mock call counts.
- Use fixtures aggressively for PDFs, page blocks, OCR outputs, and article payloads.
- For parsing, verify article-level outcomes, not just intermediary method calls.

## Test Layers

The project should use four test layers.

### 1. Domain And Unit Tests

Purpose:

- Lock down pure behavior cheaply
- Drive value objects, normalization logic, status transitions, and reconstruction rules

Examples:

- Duplicate-document detection
- Task state transitions
- Block normalization
- Tag count validation
- Focused-tag deduplication

### 2. Adapter And Contract Tests

Purpose:

- Lock down how our code talks to external systems without needing the real external system every time

Examples:

- Gmail message mapping
- Model response validation
- OCR adapter response normalization
- PDF extraction adapter output mapping

### 3. Integration Tests

Purpose:

- Verify slices across storage, services, and orchestration
- Catch boundary mistakes between parser, enrichment, and persistence

Examples:

- Import email with one PDF and persist one document
- Parse one digital sample PDF into article objects
- Resume an interrupted document after restart

### 4. End-To-End Smoke Tests

Purpose:

- Confirm the first user-visible path works from input to dashboard

Examples:

- Sample document reaches article list and detail page
- Article card shows summary and tags
- Detail page switches between English and Chinese

## Fixture Strategy

To make TDD practical here, fixtures should be treated as first-class assets.

We should prepare and keep a small private test corpus with:

- One representative digital newspaper PDF
- One representative scanned newspaper PDF
- One digital page with strong ad interference
- One cross-page article case
- One Gmail message fixture with a PDF attachment payload
- One model output fixture for tags, summary, and translation
- One OCR result fixture with bounding boxes and confidence

We should also keep smaller synthetic fixtures for focused rule tests:

- Minimal block lists for cross-column grouping
- Minimal block lists for ad-vs-article classification rules
- Minimal article objects for dashboard query tests

## Scope Of The First TDD Slice

The first implementation slice should stay intentionally narrow.

It should prove:

- The system can import one target PDF from Gmail
- The system can persist a document record without duplication
- The system can reconstruct at least one digital PDF into article objects
- The system can enrich one article with tags, summary, and translation
- The system can render the result in a minimal article list and detail page

Scanned PDF support, advanced ambiguity resolution, and recovery hardening should be tested later in the sequence, not before this slice is green.

## Recommended Test Order

The recommended order below is the actual TDD queue.

Each item should be implemented as:

- one failing test
- minimum code
- passing test
- then move on

## Phase 1 Test Queue: Foundation

These tests should come first because they define stable primitives used by the rest of the system.

### 1. Configuration Loading

Test:

- `loads required application settings from environment`

Behavior:

- Given valid environment variables, the settings object loads and exposes typed values.

Why first:

- Everything else depends on reliable configuration.

### 2. Missing Required Configuration

Test:

- `fails fast when required Gmail credentials are missing`

Behavior:

- Startup config validation should reject missing required Gmail settings with a clear error.

### 3. Document Identity

Test:

- `builds a stable document key from message id attachment id and content hash`

Behavior:

- Repeated imports of the same attachment should resolve to the same logical identity.

### 4. Task State Transition

Test:

- `transitions a task from pending to running to succeeded`

Behavior:

- Valid state transitions should succeed and invalid ones should be rejected later with separate tests.

### 5. Invalid Task Transition

Test:

- `rejects transition from succeeded back to running`

Behavior:

- Once a task is terminal, it should not silently re-enter execution.

## Phase 2 Test Queue: Gmail Ingestion

These tests should define ingestion behavior without requiring downstream parsing.

### 6. Target Email Filtering

Test:

- `selects only messages from configured senders with pdf attachments`

Behavior:

- Non-target senders and non-PDF attachments are ignored.

Test style:

- Use a fake Gmail gateway and real filtering code.

### 7. Raw Attachment Persistence

Test:

- `stores a fetched pdf attachment at the configured raw document path`

Behavior:

- A fetched attachment is written once to the expected location and linked to a document record.

### 8. Duplicate Import Prevention

Test:

- `does not create a second document for the same attachment`

Behavior:

- Importing the same Gmail message twice should not create duplicate document rows or duplicate raw files.

### 9. Import Status Recording

Test:

- `creates a pending document processing task after a successful import`

Behavior:

- Ingestion must stop at durable document creation plus task creation, not directly call parsing inline.

## Phase 3 Test Queue: Digital Parsing

These tests define the first parsing path and should be driven with one digital fixture plus a few synthetic block fixtures.

### 10. Digital Page Classification

Test:

- `classifies a text-rich selectable page as digital`

Behavior:

- A page with strong extractable text and expected text density is marked digital.

### 11. Block Normalization

Test:

- `normalizes extracted text fragments into ordered page blocks`

Behavior:

- Raw PDF extraction output is mapped into the shared block structure with coordinates and order fields.

### 12. Header And Footer Filtering

Test:

- `excludes repeating header and footer blocks from article reconstruction`

Behavior:

- Repeating page chrome should not appear inside article body text.

### 13. Title Candidate Detection

Test:

- `identifies a large leading text block as an article title candidate`

Behavior:

- The parser should detect likely titles using geometry and style clues.

### 14. Single-Page Article Reconstruction

Test:

- `reconstructs one article from title lead and body blocks on the same page`

Behavior:

- A simple same-page case becomes one article object with title and ordered body text.

### 15. Cross-Column Continuation

Test:

- `continues article body across adjacent columns when no new title intervenes`

Behavior:

- The reconstruction logic should connect continuation blocks rather than truncating early.

### 16. Cross-Page Continuation

Test:

- `reconstructs an article that continues onto a later page`

Behavior:

- The reconstruction logic should combine page-local and later-page continuation into one article.

### 17. Ad Filtering

Test:

- `does not reconstruct a large ad block as a news article`

Behavior:

- Obvious ad regions should be excluded from article outputs.

### 18. Parser Integration Slice

Test:

- `parses a representative digital newspaper pdf into article objects`

Behavior:

- Given a real sample PDF fixture, the parser returns a non-empty set of article objects that satisfy minimum structural expectations.

Minimum assertions:

- At least one article exists
- Titles are not empty
- Body text is longer than a minimal threshold
- Repeating headers do not dominate article text

## Phase 4 Test Queue: Article Enrichment

These tests should be written against article objects, not pages.

### 19. Tag Count Validation

Test:

- `accepts between three and eight generated tags for an article`

Behavior:

- Enrichment output is valid only when tag count stays inside the approved range.

### 20. Tag Output Rejection

Test:

- `rejects enrichment output with fewer than three tags`

Behavior:

- Invalid provider output should not be silently persisted as complete.

### 21. Summary Persistence

Test:

- `stores a chinese summary generated for an article`

Behavior:

- A successful summary result becomes durable article data.

### 22. Translation Persistence

Test:

- `stores a full chinese translation generated for an article`

Behavior:

- Full article translations are stored separately from summaries.

### 23. Partial Enrichment

Test:

- `marks an article as partial when summary succeeds and translation fails`

Behavior:

- One failed enrichment step should not erase successful enrichment steps.

### 24. Enrichment Integration Slice

Test:

- `enriches a reconstructed article with tags summary and translation`

Behavior:

- One article object can move through the full enrichment path and persist all outputs.

## Phase 5 Test Queue: Dashboard

These tests should define behavior at the user-facing read model.

### 25. Focused Tag Selection

Test:

- `returns recent articles matching focused tags before the general feed`

Behavior:

- Focused-tag logic should select matching recent articles for the home page.

### 26. Focused Tag Deduplication

Test:

- `shows an article once even when it matches multiple focused tags`

Behavior:

- The focused section is article-based, not tag-entry-based.

### 27. All-Articles Query

Test:

- `filters articles by source and date range`

Behavior:

- The main feed query honors source and date filters together.

### 28. Detail Language Switching

Test:

- `returns english and chinese article views from the same article record`

Behavior:

- The detail page can render either language without separate article records.

### 29. Card Without Image

Test:

- `renders article card data without requiring an image`

Behavior:

- Missing image data does not break the card read model.

### 30. Dashboard Smoke Test

Test:

- `shows an imported and enriched article on the home page and detail page`

Behavior:

- One end-to-end slice reaches visible UI state.

## Later Test Queue: Scanned PDFs And Ambiguity Resolution

These tests should wait until the first digital slice is working.

### 31. Scanned Page Classification

Test:

- `classifies an image-heavy page with weak text extraction as scanned`

### 32. OCR Block Normalization

Test:

- `normalizes ocr output into the shared block model`

### 33. Low Confidence Marking

Test:

- `marks a scanned article as low confidence when ocr quality is below threshold`

### 34. Ambiguity Resolution For Continuation

Test:

- `uses ambiguity resolution to connect two uncertain continuation block groups`

### 35. Ambiguity Resolution For Ad Detection

Test:

- `downgrades an uncertain article candidate to ad when ambiguity resolution rejects it`

## Later Test Queue: Recovery And Hardening

These tests should follow after the core path exists.

### 36. Restart Recovery

Test:

- `requeues a stale running task after worker restart`

### 37. Artifact Reuse

Test:

- `reuses completed page artifacts during a resumed document run`

### 38. Duplicate Retry Safety

Test:

- `does not duplicate articles when a document is resumed after partial completion`

### 39. User-Visible Status Reporting

Test:

- `reports document status as partial when some articles fail enrichment`

## Recommended First Sprint TDD Sequence

For the first coding sprint, the exact TDD sequence should be:

1. `loads required application settings from environment`
2. `fails fast when required Gmail credentials are missing`
3. `builds a stable document key from message id attachment id and content hash`
4. `transitions a task from pending to running to succeeded`
5. `rejects transition from succeeded back to running`
6. `selects only messages from configured senders with pdf attachments`
7. `stores a fetched pdf attachment at the configured raw document path`
8. `does not create a second document for the same attachment`
9. `creates a pending document processing task after a successful import`
10. `classifies a text-rich selectable page as digital`
11. `normalizes extracted text fragments into ordered page blocks`
12. `excludes repeating header and footer blocks from article reconstruction`
13. `identifies a large leading text block as an article title candidate`
14. `reconstructs one article from title lead and body blocks on the same page`
15. `parses a representative digital newspaper pdf into article objects`
16. `accepts between three and eight generated tags for an article`
17. `stores a chinese summary generated for an article`
18. `stores a full chinese translation generated for an article`
19. `enriches a reconstructed article with tags summary and translation`
20. `shows an imported and enriched article on the home page and detail page`

This is intentionally smaller than the full backlog. It is the minimum end-to-end path worth proving first.

## What We Should Not Test First

To keep the TDD loop healthy, these should not be part of the first cycle:

- Complex scanned-PDF ambiguity prompts
- Final dashboard visual polish
- Large-scale retry orchestration
- Multiple newspaper formats at once
- Full production Gmail sync edge cases
- Performance optimization

These matter, but they should come after the first vertical slice is working.

## Definition Of A Good Failing Test In This Project

Each new failing test should:

- Express one business behavior
- Fail because the behavior is missing
- Use the real domain model whenever possible
- Avoid over-specifying implementation details
- Be small enough that the minimal passing code is obvious

Examples of good test intent here:

- `does not create a second document for the same attachment`
- `reconstructs one article from title lead and body blocks on the same page`
- `shows an article once even when it matches multiple focused tags`

Examples of weak test intent here:

- `calls parser helper twice`
- `invokes repository save`
- `passes expected mock arguments to service`

## Exit Criteria For The TDD Plan

This TDD plan is good enough to start implementation when:

- The first sprint sequence is explicit
- Each phase has concrete behavior-level tests
- External boundaries are clearly identified for fakes
- The first digital vertical slice is prioritized ahead of scanned complexity

## Summary

The first TDD target is not "the whole newspaper system." It is one narrow but real flow:

`import one target PDF -> persist it once -> reconstruct at least one article -> enrich it -> show it in the dashboard`

If we stay disciplined around that flow, the rest of the system can grow without losing clarity.
