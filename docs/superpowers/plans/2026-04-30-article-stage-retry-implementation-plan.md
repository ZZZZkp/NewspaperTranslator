# Article Stage Retry Implementation Plan

Date: 2026-04-30

Related documents:

- [Article Stage Retry And Identity Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-30-article-stage-retry-design.md)
- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)
- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)
- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)

## Goal

This plan turns the approved article-stage retry design into a staged delivery order that reaches a more correct processing model:

- document parse success remains durable once markdown and article persistence succeed
- article enrichment becomes independently schedulable and independently retryable
- successful unchanged articles are not enriched again automatically
- repeated parses of the same source file can map back to the same logical article
- the frontend and operator APIs can show article source filename and page numbers

## Execution Status

Status on 2026-04-30: planning approved, implementation not started yet.

The repository already has several foundations this plan can reuse:

- durable raw document import and document deduplication
- durable parse runs, fragments, continuation matches, and final articles
- durable article enrichment run history with `input_hash`
- document-level scheduler orchestration and retry semantics
- backend query and frontend surfaces for article and document views

The main gap is that article enrichment still lives inside the document success path. This plan moves that responsibility to a dedicated article-stage control plane without redesigning the whole parse pipeline.

## Current Starting Point

The current behavior is technically functional but semantically wrong for this stage boundary:

- `process_document(...)` treats parse and enrich as one document workflow
- `enrich_document_articles(...)` enriches every latest article in a document immediately
- one failed article can mark the whole document `failed_retryable`
- the next retry path re-runs document-level enrichment for all articles in the document
- successful unchanged articles are not protected from repeat enrichment
- article-facing queries do not yet expose durable source filename and page-number metadata

The implementation should preserve everything that already works well:

- current parse persistence model
- current article enrichment history model
- current scheduler lock and retry patterns
- current dashboard architecture

## Delivery Principles

Implementation should follow these principles:

1. Persist identity and source metadata before changing scheduling behavior.
   Scheduling should not depend on inferred state that is not yet durable.

2. Keep document and article retry semantics clearly separated.
   Document retries should remain for document stages only.

3. Reuse the current processing-state patterns.
   New article-stage control-plane code should look and behave like existing document-stage code where practical.

4. Make deduplication observable in tests before wiring the scheduler.
   The highest-risk logic is deciding whether a logical article should be re-enqueued.

5. Ship backend correctness before frontend polish.
   UI work should consume stable query models, not drive them.

## Recommended Delivery Order

### Slice 1: Persist Source Page Metadata

Add the durable page metadata needed for article identity and frontend display.

Scope:

- extend the parse persistence schema so fragment page numbers are stored durably
- ensure final articles can resolve all contributing source pages
- update parse-result recording helpers in `article_store.py`
- update parse-building code in `pdf.py` and related parse models as needed
- add query helpers that can return article source pages cheaply

Why first:

- article identity matching depends on durable page overlap
- frontend source-page display should not be reconstructed from transient parse state

Likely code areas:

- `src/newspaper_translator/pdf.py`
- `src/newspaper_translator/article_store.py`
- `src/newspaper_translator/migrations/`
- parse-related tests

Exit criteria:

- every persisted fragment has a durable page number
- every final article can resolve one or more source page numbers
- cross-page merged articles expose all contributing pages

### Slice 2: Introduce Logical Article Identity

Add stable article identity across repeated parses of the same source file.

Scope:

- add durable `article_key` persistence
- add identity-assignment logic after parse persistence completes
- match only within the same source document lineage
- implement the first matching heuristic:
  - same original file
  - shared page overlap
  - normalized title or opening similarity >= 90 percent
- keep deterministic behavior through narrow, tested matching rules

Why second:

- article-stage scheduling and deduplication need a stable logical identity
- doing this before queue work keeps the state model understandable

Likely code areas:

- `src/newspaper_translator/article_store.py`
- `src/newspaper_translator/article_pipeline.py`
- `src/newspaper_translator/document_processing.py`
- migrations and repository tests

Exit criteria:

- repeated parses of the same source file can reuse `article_key`
- unmatched articles get new `article_key` values
- identity assignment is covered by same-page and cross-page tests

### Slice 3: Add Article-Stage Processing Persistence

Create the control-plane table and repository helpers for article enrichment work.

Scope:

- add a migration for `article_processing_runs` or equivalent
- add helpers to:
  - create or upsert article processing state
  - claim one article safely
  - mark article success
  - mark retryable or terminal failure
  - request manual retry
  - list eligible article work in priority order
  - recover stale `running` article work
- mirror existing document-processing field semantics where practical

Why third:

- queue semantics should be proven before changing scheduler flow
- this creates one clear place for article-stage state transitions

Likely code areas:

- `src/newspaper_translator/document_processing.py` or a new dedicated article-processing module
- `src/newspaper_translator/migrations/`
- processing-state tests

Exit criteria:

- one article processing item can move from `pending` to `running` to `succeeded`
- retryable and terminal failures follow the same ceiling semantics as document processing
- manual retry and stale-run recovery are both supported

### Slice 4: Decouple Document Success From Article Enrichment

Change the document processing flow so parse success no longer depends on all article enrichments succeeding in the same document pass.

Scope:

- update `process_document(...)` so document completion is based on `parse_persist` success
- replace immediate all-article enrichment execution with article-work enqueue or refresh behavior
- keep document failure semantics only for document-stage errors
- remove the current behavior where one failed article marks the document `failed_retryable`

Why fourth:

- once article processing persistence exists, document orchestration can safely stop owning article enrichment outcome

Likely code areas:

- `src/newspaper_translator/document_processing.py`
- scheduler tests
- document-processing tests

Exit criteria:

- a document with successful parse persistence can finish successfully even if one article still needs enrichment retry
- document retry endpoints remain meaningful only for document-stage failures

### Slice 5: Add Article Enrichment Deduplication And Requeue Rules

Implement the logic that decides whether a logical article needs enrichment now.

Scope:

- compute current article input hash for scheduling decisions
- if a logical article's current version already has a matching successful enrichment result, skip enqueue
- if the logical article changed, enqueue only that logical article
- add a runtime guard to avoid writing duplicate successful enrichment runs for unchanged input
- preserve manual force-retry as an override path

Why fifth:

- this slice delivers the core business correction the user asked for
- it is easiest to verify after article-stage state already exists

Likely code areas:

- `src/newspaper_translator/article_enrichment.py`
- `src/newspaper_translator/article_store.py`
- article-processing orchestration code

Exit criteria:

- successful unchanged articles do not re-enter automatic enrichment
- changed current versions of a logical article do re-enter enrichment
- runtime duplicate successful-run creation is blocked or safely short-circuited

### Slice 6: Extend The Scheduler To Process Article Work

Teach the scheduler to process both document-stage work and article-stage work.

Scope:

- add eligible article-work selection in scheduler ticks
- add article claim and execution paths
- prioritize article `manual_retry_requested` ahead of `pending` and `failed_retryable`
- keep scheduler accounting accurate for mixed work
- recover stale article work during startup maintenance or scheduled recovery

Why sixth:

- queueing and deduplication should already be correct before timer-driven background execution expands
- this keeps scheduler complexity layered on top of proven state transitions

Likely code areas:

- `src/newspaper_translator/document_processing.py`
- `src/newspaper_translator/worker.py`
- CLI or scheduler tests

Exit criteria:

- scheduler ticks can process pending article enrichment independently of document retries
- article-stage retries happen automatically without forcing document reprocessing
- stale article tasks recover safely

### Slice 7: Add Manual Article Retry Entry Points

Expose focused operator controls for article-stage remediation.

Scope:

- add CLI entrypoints such as:
  - `retry-article-enrich --article-id ...`
  - or `--article-key ...`
- add backend API support for manual article retry
- choose the identifier surface that best matches current UI routing and storage boundaries
- keep document retry and article retry clearly separated in naming and behavior

Why seventh:

- manual controls are valuable once automatic paths are working
- the API surface should reflect settled backend semantics

Likely code areas:

- `src/newspaper_translator/manage.py`
- `src/newspaper_translator/web.py`
- API tests
- CLI tests

Exit criteria:

- one logical article can be manually returned to an eligible retry state
- manual article retry does not affect sibling articles or document processing state

### Slice 8: Expose Source Metadata And Article-Stage Status In Queries

Update the query layer so UI surfaces can show article origin and article-stage processing state.

Scope:

- extend article card and article detail view models with:
  - source filename
  - source page numbers
  - article processing status
  - article processing error when relevant
- add operator query support for article-stage exceptions
- keep response shapes UI-ready and avoid leaking raw storage joins

Why eighth:

- frontend work should sit on top of backend-ready view models
- this slice closes the gap between durable backend state and observable product state

Likely code areas:

- `src/newspaper_translator/api/queries.py`
- serializer helpers
- query tests

Exit criteria:

- article list and detail queries include source filename and page numbers
- operator queries can distinguish document-stage and article-stage exceptions

### Slice 9: Update Frontend Reading And Operator Surfaces

Show the new metadata and article-stage exception flows in the UI.

Scope:

- add source filename and page numbers to article cards where space permits
- add source filename and page numbers to article detail metadata rail
- add article-stage exception views or sections in operator pages
- add manual article retry UI where appropriate
- preserve reading-first layout priorities

Why ninth:

- the backend contract should already be stable
- this keeps frontend work focused on presentation and interaction rather than semantics

Likely code areas:

- `frontend/`
- frontend tests if present

Exit criteria:

- readers can see where an article came from
- operators can see article-stage failures separately from document-stage failures
- manual article retry can be triggered through the UI if included in this slice

## Parallel Work Strategy

Some work can proceed in parallel after the right blocking slices land.

### After Slice 1 begins

Parallelizable work:

- migration work for source page persistence
- parse-model updates for carrying page numbers through to storage

Constraint:

- both lanes must agree on the final page metadata shape before query work starts

### After Slice 3 completes

Parallelizable work:

- deduplication logic in enrichment orchestration
- scheduler integration for article-stage work

Constraint:

- both lanes must share the same article processing state machine and retry semantics

### After Slice 8 begins

Parallelizable work:

- article-facing query updates
- operator query updates
- frontend rendering of source metadata

Constraint:

- response field names should be finalized before frontend polish expands

## Testing Strategy

Testing should stay close to each slice rather than being deferred to one final pass.

### Repository And Migration Tests

- migration adds page metadata persistence
- migration adds logical article identity persistence
- migration adds article-stage processing persistence
- indexes exist for queue scans and latest-success lookups

### Identity Tests

- same file plus shared page plus similar normalized title inherits `article_key`
- same file plus shared page plus similar opening inherits `article_key`
- similar text without page overlap does not inherit identity
- unrelated same-page short articles do not false-match under threshold tests

### Orchestration Tests

- document parse success no longer depends on article enrich success
- changed logical article versions enqueue only themselves
- unchanged successful logical articles are skipped
- duplicate successful enrich-run creation is blocked or short-circuited

### Scheduler Tests

- article work is selected in the expected priority order
- automatic article retry stops after two retries
- stale article work recovers safely
- document-stage work and article-stage work can coexist in one scheduler cycle

### Query And API Tests

- article list includes source filename and page numbers
- article detail includes full page list and article-stage status
- operator APIs separate document-stage and article-stage failures
- manual article retry endpoints update state correctly

### Frontend Tests

- article metadata renders source filename and pages correctly
- article-stage exception UI distinguishes from document-stage exceptions
- retry actions refresh visible state correctly

## Suggested Commit Strategy

To keep reviewable increments small, prefer commits aligned with the major slices:

1. page metadata persistence
2. logical article identity
3. article-stage processing schema and helpers
4. document and scheduler decoupling
5. deduplication and retry behavior
6. API and query exposure
7. frontend integration

## Risks And Mitigations

### 1. Identity Matching Is Too Weak

Risk:

- the 90 percent similarity rule may miss some legitimate same-article cases

Mitigation:

- keep matching narrow for the first release
- cover obvious regression cases in tests
- preserve schema flexibility so heuristics can evolve later

### 2. Identity Matching Is Too Aggressive

Risk:

- short same-page articles may be incorrectly merged into one logical article

Mitigation:

- require both same-file lineage and page overlap
- allow either title or opening match, but test short ambiguous cases

### 3. Scheduler Complexity Expands Too Early

Risk:

- mixing article-stage and document-stage work in the scheduler can make debugging harder

Mitigation:

- prove article-stage persistence and state transitions before scheduler integration
- keep queue semantics close to the existing document-processing model

### 4. Frontend Surfaces Expose Half-Stable Semantics

Risk:

- UI work may leak implementation details if query contracts change too often

Mitigation:

- finish backend query shapes before significant frontend work
- keep source metadata and article-stage status as explicit view-model fields

## Definition Of Done

This implementation is complete when all of the following are true:

- a document with successful parse persistence is not forced back into document retry because one article enrich failed
- logical articles can be recognized across repeated parses of the same source file
- unchanged successful articles are not automatically re-enriched
- changed logical articles can be independently re-enriched
- article-stage retries happen automatically up to the approved retry limit
- operators can manually retry one article without retrying the whole document
- article list and detail surfaces show source filename and page numbers
- operator views can distinguish document-stage failures from article-stage failures

## Recommended First Build Target

The highest-value first milestone is Slices 1 through 5 together:

- persist source pages
- assign `article_key`
- add article-stage processing persistence
- decouple document success from article enrich success
- enforce enrichment deduplication and requeue rules

That milestone delivers the core correctness fix even before scheduler expansion and frontend updates are complete.
