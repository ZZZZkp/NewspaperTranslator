# Article Processing Workbench Design

Date: 2026-05-02

Related documents:

- [Article Stage Retry And Identity Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-30-article-stage-retry-design.md)
- [Article Stage Retry Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-04-30-article-stage-retry-implementation-plan.md)
- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)
- [Newspaper Translator Progress Summary](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/status/2026-04-30-progress-summary.md)

## Overview

The repository already exposes article-stage processing state through the backend:

- `article_processing_runs` persists current article-stage state
- the worker can schedule, recover, and retry article-stage work
- the CLI can inspect and retry article processing
- the web backend already exposes article-processing list, detail, and retry endpoints

The current gap is product-facing. The frontend operator workbench only exposes document-level processing views. Operators can inspect document-level parse state, but they cannot directly scan article-stage failures, inspect page-level source metadata, or request article-level retries from the workbench.

This design extends the existing operator workbench so article processing becomes a first-class operator surface without creating a second admin product.

## Goals

- Add article-stage visibility to the existing operator workbench
- Keep document-level and article-level operations within one shared workbench entry point
- Let operators scan all article-processing items by default
- Provide an independent article-processing detail page for troubleshooting and retry
- Preserve a clear distinction between reading views and operator views
- Reuse existing frontend interaction patterns where practical

## Non-Goals

- Replacing the existing card-based operator workbench layout with a table-based UI
- Merging document-processing and article-processing items into one mixed list
- Embedding full article-processing detail directly inside document detail as the only access path
- Combining article reading detail and article processing detail into one page
- Adding new backend retry semantics beyond the existing manual article retry endpoint
- Adding batch retry, ignore, terminate, or bulk remediation actions in this slice

## Product Decisions

The user-approved product decisions for this slice are:

- article processing is merged into the current workbench instead of becoming a new top-level product area
- the workbench uses two internal tabs:
  - `文档处理`
  - `文章处理`
- the article-processing list defaults to all article-processing items rather than only failures
- article-processing uses an independent detail page rather than inline expansion

## Why This Should Be One Workbench

The system now has two operational objects:

1. `document_processing_runs`
   - answers where one imported PDF is in the document-level workflow
2. `article_processing_runs`
   - answers where one logical article is in the article enrichment workflow

These are not two unrelated systems. They are two observation layers of the same pipeline. A document can succeed at `parse_persist` while one or more articles remain pending, running, or failed in `article_enrich`.

Creating a separate admin entry point for article processing would imply a larger product boundary than the pipeline actually has. The clearer model is one workbench with two operator views:

- document view for document-stage orchestration
- article view for article-stage troubleshooting

## Information Architecture

The existing primary navigation remains unchanged:

- `阅读首页`
- `处理工作台`

Inside `处理工作台`, the content area gains a second-level switch:

- `文档处理`
- `文章处理`

The operator workbench routes become:

- `#documents`
  - document-processing list
- `#document/<document_key>`
  - document-processing detail
- `#articles-processing`
  - article-processing list
- `#article-processing/<article_key>`
  - article-processing detail

This route split intentionally keeps reading and operations separate:

- `#article/<article_id>` is for reading content
- `#article-processing/<article_key>` is for troubleshooting processing state

This distinction matters because the two views have different primary identifiers, page intent, and action models.

## Article-Processing List View

The article-processing list follows the existing workbench card-list pattern rather than introducing a new table UI.

### Why Card Layout Stays

The current frontend already uses card grids and card-to-detail navigation for:

- article reading list
- document-processing list

Reusing that pattern reduces implementation risk and keeps the workbench visually coherent. This slice should expose article-stage operations, not redesign the frontend shell.

### Default Dataset

The default article-processing list shows all article-processing items, including:

- `pending`
- `running`
- `failed_retryable`
- `manual_retry_requested`
- `failed_terminal`
- `succeeded`

Operators can then narrow the list through filters, but the starting point is full operational visibility rather than exception-only visibility.

### Required Card Content

Each article-processing card should show:

- article title from `title_en`
- source name
- publication date
- original filename
- source page numbers
- current status
- current step
- automatic failure count
- latest error summary

These fields are sufficient for the two primary operator actions:

- scan the list for failures, long-running items, and problem clusters
- decide whether to open detail and request retry

### Filters

The minimum filter set for this slice is:

- article status
- source name
- publication date from
- publication date to

The filter behavior should mirror the current document-processing experience:

- empty values mean no filter
- the page remains usable when no filters are selected
- meta text shows the current result count

### List Behavior

The article-processing list behavior matches the existing document-processing list:

- cards are clickable
- clicking a card opens the independent article-processing detail page
- the page shows result-count metadata such as the current number of visible records

## Article-Processing Detail View

The article-processing detail page is independent from the reading detail page and should structurally mirror the current document-detail layout where practical.

### Layout Direction

The recommended structure is:

- left column for state summary and actions
- right column for identity, source, and troubleshooting context

This preserves workbench consistency while avoiding a full new layout system.

### Required Detail Sections

The article-processing detail page should include:

#### 1. Status Summary

Show:

- `status`
- `current_step`
- `automatic_failure_count`
- `updated_at`

#### 2. Error And Retry

Show:

- `latest_error_summary`
- `last_error_message`

Action:

- `请求重试`

This slice intentionally exposes only one operator action because the backend already supports manual retry and no other operator controls have been approved for this milestone.

#### 3. Article Identity

Show:

- article title
- source name
- original filename
- publication date
- source page numbers

This section exists so operators can answer:

- which article failed
- which source file it came from
- which pages are relevant for debugging parse or enrichment quality

#### 4. Related Navigation

Provide clear links to:

- the owning document detail page
- the article reading detail page

These links maintain workflow continuity without collapsing the purposes of the pages into one overloaded view.

## Relationship Between Reading And Operations

This slice must preserve a clean page-purpose boundary:

- article reading detail exists for reading translated and original content
- article-processing detail exists for processing status, retry, and troubleshooting
- document-processing detail exists for document-level import and parse orchestration

The article-processing detail page should not attempt to become a second reading page. It may link to the reading view, but it should not replicate the reading layout or bilingual body presentation. Otherwise the page will mix two unrelated tasks:

- reading the article
- repairing pipeline execution

Keeping those tasks separate leads to a clearer operator experience and a smaller implementation surface.

## Frontend Implementation Boundaries

This slice should extend the current frontend shell instead of refactoring it broadly.

### Reuse Existing Structures

The implementation should reuse:

- the current primary workbench entry point
- the current hash-routing approach in `frontend/app.js`
- the current workbench card-grid pattern
- the current detail-page structural pattern
- the existing document retry request-and-refresh interaction style

### Additions In Scope

The main frontend additions are:

- a second-level workbench tab state
- article-processing list section markup
- article-processing detail section markup
- article-processing filter controls
- route handlers for article-processing list and detail
- retry action wiring for article-processing detail

### Not In Scope For This Slice

Do not expand scope into:

- document and article mixed cards in one list
- batch retry or bulk actions
- inline expandable article-processing cards
- broad frontend shell redesign
- shared unified detail pages between reading and operations

## Interaction Flow

The intended operator flow is:

1. User enters the workbench at `#documents`
2. User switches to `#articles-processing`
3. Frontend loads the article-processing list with the default all-items dataset
4. User filters or scans the list
5. User clicks one article-processing card
6. Frontend opens `#article-processing/<article_key>`
7. User inspects state, source context, and error details
8. User optionally requests manual retry
9. Frontend refreshes the current detail and list state
10. User can jump to the owning document detail or the article reading page

This intentionally mirrors the existing document-processing interaction style so operators do not need to learn a second workflow.

## API Expectations

This slice is designed to consume the existing backend API surface rather than require new control-plane behavior.

The frontend should rely on:

- article-processing list endpoint
- article-processing detail endpoint
- article-processing retry endpoint

If response-shaping gaps are discovered during implementation, the backend may add small serialization adjustments, but the design assumes the existing article-processing APIs remain the core contract.

## Error Handling

Frontend behavior should stay lightweight and consistent with the current workbench:

- failed list fetch shows a readable status message
- failed detail fetch shows a readable status message
- retry action shows pending feedback while the request is in flight
- successful retry refreshes both detail and list state
- route errors fall back to a safe workbench state rather than leaving the page blank

This slice does not require advanced optimistic updates or offline state handling.

## Testing Expectations

Implementation should add or extend tests in these areas:

- backend query coverage for any article-processing view-shape adjustments
- `test_web.py` coverage for article-processing list, detail, and retry responses
- `test_frontend_static.py` coverage for new sections, controls, and route anchors
- targeted frontend behavior checks for article-processing routing and retry wiring where practical

The goal is to verify the new workbench slice without forcing a larger frontend test harness redesign.

## Recommended Delivery Outcome

This slice is complete when:

- the workbench contains `文档处理` and `文章处理` as internal tabs
- article-processing defaults to a full list of article-processing items
- operators can open an article-processing detail page from that list
- operators can request retry from article-processing detail
- operators can jump from article-processing detail to the owning document detail
- operators can jump from article-processing detail to the article reading page
- the frontend remains visually and behaviorally consistent with the existing workbench shell
