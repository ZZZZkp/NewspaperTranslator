# Article Processing Workbench Implementation Plan

Date: 2026-05-02

Related documents:

- [Article Processing Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-02-article-processing-workbench-design.md)
- [Article Stage Retry And Identity Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-30-article-stage-retry-design.md)
- [Article Stage Retry Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-04-30-article-stage-retry-implementation-plan.md)
- [Dashboard And Operator Workbench Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-04-29-dashboard-and-operator-workbench-implementation-plan.md)

## Goal

This plan turns the approved article-processing workbench design into a staged delivery order that reaches a usable operator-facing frontend slice:

- article processing becomes visible inside the existing workbench
- operators can switch between document-level and article-level operational views
- article-processing defaults to a full operational list rather than an exception-only subset
- operators can inspect article-stage detail, request retry, and jump to related document and reading pages
- the implementation reuses the current frontend shell rather than redesigning it

## Execution Status

Status on 2026-05-02: planning approved, implementation not started yet.

The repository already has most backend foundations required for this slice:

- article-processing persistence in `article_processing_runs`
- worker-driven article-stage scheduling and stale-run recovery
- manual article retry behavior
- article-processing list, detail, and retry endpoints
- a frontend shell with hash routing, card grids, detail views, and document-processing operator screens

The main remaining gap is frontend product wiring rather than backend control-plane behavior.

## Current Starting Point

The project is in a favorable position for this slice because the core article-stage model already exists.

Current strengths:

- `web.py` already exposes article-processing endpoints
- `api/queries.py` already provides article-processing detail shaping
- `frontend/app.js` already implements hash-based list/detail flows for reading and document-processing views
- `frontend/index.html` and `frontend/styles.css` already define the workbench shell, card grids, and detail layout patterns

Current limitations:

- there is no second-level workbench switch between document and article operations
- there is no article-processing list page in the frontend
- there is no article-processing detail page in the frontend
- there is no article-processing retry action wired into the workbench
- current operator navigation does not distinguish reading detail from article-processing detail

## Delivery Principles

Implementation should follow these principles:

1. Extend before refactor.
   This slice should add article-processing surfaces to the existing workbench rather than redesigning the shell.

2. Route clarity over convenience.
   Reading routes and operator routes should stay distinct even when they reference the same article lineage.

3. Reuse current interaction patterns.
   Article retry and detail refresh should behave like the existing document retry flow where practical.

4. Keep each slice independently testable.
   Every stage should end with a visible or queryable increment.

5. Avoid broad UI ambition.
   The goal is a correct and coherent operator surface, not a full workbench redesign.

## Recommended Delivery Order

### Slice 1: Confirm And Tighten API View Contracts

Review the existing article-processing API shapes against the newly approved frontend requirements and make only the smallest backend adjustments needed.

Scope:

- verify that article-processing list responses contain all fields needed for cards:
  - title
  - source name
  - publication date
  - original filename
  - source page numbers
  - status
  - current step
  - failure count
  - latest error summary
- verify that article-processing detail responses contain all fields needed for the independent detail page and related jumps
- add or refine serializer/query helpers only where the frontend contract is incomplete
- keep the backend contract aligned with the approved workbench routes and sections

Why first:

- the frontend should consume stable view models rather than reverse-engineer control-plane storage
- this de-risks later frontend work and keeps route design grounded in real response shapes

Likely code areas:

- `src/newspaper_translator/api/queries.py`
- `src/newspaper_translator/web.py`
- `tests/test_api_queries.py`
- `tests/test_web.py`

Exit criteria:

- article-processing list responses expose all required card fields
- article-processing detail responses expose all required detail and navigation fields
- backend tests cover any adjusted response shapes

### Slice 2: Add Workbench Tab And Route Foundations

Introduce the internal `文档处理` / `文章处理` workbench switch and define the route boundaries for the new article-processing views.

Scope:

- extend the existing workbench navigation model with a second-level tab switch
- add route handling for:
  - `#articles-processing`
  - `#article-processing/<article_key>`
- preserve existing routes for:
  - `#documents`
  - `#document/<document_key>`
  - `#article/<article_id>`
- ensure unknown or partial article-processing routes fail safely back into the workbench

Why second:

- the rest of the frontend work depends on stable route boundaries
- route separation between reading and operations is the most important structural decision in this slice

Likely code areas:

- `frontend/index.html`
- `frontend/app.js`
- `tests/test_frontend_static.py`

Exit criteria:

- the workbench visibly supports `文档处理` and `文章处理` as internal tabs
- the new article-processing routes are recognized and do not conflict with existing article reading routes
- route fallbacks remain safe and readable

### Slice 3: Build The Article-Processing List View

Implement the article-processing list page using the existing card-grid workbench pattern.

Scope:

- add article-processing filter controls in the sidebar
- add the article-processing list section in the main content area
- load the default all-items article-processing dataset
- render article-processing cards with the approved field set
- show list metadata such as visible result count
- keep loading, empty, and error states consistent with the current workbench experience

Why third:

- once routes exist, the list page becomes the first usable operator-facing article-processing increment
- it gives immediate value even before the detail page is complete

Likely code areas:

- `frontend/index.html`
- `frontend/app.js`
- `frontend/styles.css`
- `tests/test_frontend_static.py`

Exit criteria:

- a user can enter `#articles-processing` and see article-processing items
- the page defaults to all article-processing statuses
- card content matches the approved operational fields
- basic list states are readable and consistent with the existing workbench

### Slice 4: Add Article-Processing Filters And Query Wiring

Wire the article-processing list filters into the frontend load flow and corresponding backend query parameters.

Scope:

- support article status filtering
- support source-name filtering
- support publication-date-from filtering
- support publication-date-to filtering
- update list reload behavior and status messaging after filter changes
- keep filter behavior parallel to the current document-processing and dashboard filtering style

Why fourth:

- the first list can land with the default dataset, but the workbench is not operationally useful until narrowing controls work
- this slice isolates filter-state handling from detail-page logic

Likely code areas:

- `frontend/app.js`
- `src/newspaper_translator/web.py`
- `src/newspaper_translator/api/queries.py`
- `tests/test_api_queries.py`
- `tests/test_web.py`

Exit criteria:

- operators can narrow article-processing items by the approved filter set
- the current result count updates after filtering
- empty filtered states remain explicit and understandable

### Slice 5: Build The Independent Article-Processing Detail View

Implement a dedicated article-processing detail page that mirrors the current document-detail structure without becoming a reading page.

Scope:

- add article-processing detail section markup
- render:
  - status summary
  - error and retry block
  - article identity block
  - related navigation block
- keep the left-right detail structure aligned with the current document detail page
- ensure article-processing detail remains operationally focused rather than content-reading focused

Why fifth:

- the list page is useful for scanning, but this slice is where troubleshooting and operator decision-making actually happen
- the detail page needs to land before retry wiring can be completed cleanly

Likely code areas:

- `frontend/index.html`
- `frontend/app.js`
- `frontend/styles.css`
- `tests/test_frontend_static.py`

Exit criteria:

- clicking an article-processing card opens an independent detail page
- the detail page exposes the approved state, identity, and error sections
- the page is clearly distinct from the reading detail page

### Slice 6: Wire Retry And Related Navigation

Attach the operational actions and cross-page jumps that make the detail page actionable.

Scope:

- wire `请求重试` to the article-processing retry endpoint
- refresh detail state after a retry request
- refresh article-processing list state after a retry request where practical
- add a jump from article-processing detail to the owning document detail page
- add a jump from article-processing detail to the article reading detail page
- keep button behavior and in-flight messaging consistent with current document retry patterns

Why sixth:

- actions should be layered on top of a stable detail view
- related navigation is easier to validate once the detail page shape already exists

Likely code areas:

- `frontend/app.js`
- `frontend/index.html`
- `tests/test_web.py`
- `tests/test_frontend_static.py`

Exit criteria:

- operators can request article retry from the detail page
- detail state refreshes after retry
- operators can jump to both the owning document and the reading article views
- the interaction feels parallel to the existing document retry flow

### Slice 7: Shared Workbench Polish And Regression Coverage

Tighten the combined workbench experience and close the main regressions introduced by the new tabbed operator model.

Scope:

- make document-processing and article-processing tabs visually coherent
- verify section visibility toggles across dashboard, document, and article-processing routes
- standardize status messages and lightweight error copy
- verify that new workbench state does not break current reading flows
- add or update regression tests for key route and section combinations

Why seventh:

- the new operator slice touches shared navigation and page visibility logic
- a dedicated polish and regression pass reduces the risk of subtle route-state breakage

Likely code areas:

- `frontend/app.js`
- `frontend/index.html`
- `frontend/styles.css`
- `tests/test_frontend_static.py`
- any affected backend tests if response copy or route expectations change

Exit criteria:

- the workbench feels like one coherent operator area rather than two bolted-on screens
- existing document-processing flows still work cleanly
- existing reading flows still work cleanly
- key route/state regressions are covered by tests

## Parallel Work Strategy

Some work can proceed in parallel once the route and contract boundaries are stable.

### After Slice 1 completes

Parallelizable work:

- frontend route and section scaffolding
- backend filter contract refinement if minor response gaps remain

Constraint:

- the frontend should not assume fields that the backend contract has not confirmed

### After Slice 2 completes

Parallelizable work:

- article-processing list rendering
- article-processing detail markup scaffolding

Constraint:

- both paths should share the same naming and visibility conventions for workbench sections

### After Slice 5 completes

Parallelizable work:

- retry wiring
- cross-navigation polish
- regression-test expansion

Constraint:

- action wiring should not force another route model change once detail structure is in place

## Testing Strategy

Testing should stay focused on the areas this slice actually changes.

Backend:

- query tests for any article-processing list/detail shape adjustments
- web endpoint tests for article-processing list, detail, retry, and filter handling

Frontend:

- static structure tests for new workbench tabs, sections, controls, and anchors
- route-behavior coverage where current tests already exercise shell assumptions
- regression checks that existing document and reading views remain reachable

Manual verification:

- switch between `阅读首页` and `处理工作台`
- switch between `文档处理` and `文章处理`
- open one article-processing detail page
- request retry for one article-processing item
- jump from article-processing detail to:
  - the owning document detail page
  - the article reading page

## Recommended First Implementation Cut

The smallest high-value initial merge should include:

1. route foundations for `#articles-processing` and `#article-processing/<article_key>`
2. the internal workbench tab switch
3. the article-processing list with default all-items loading
4. the article-processing detail page without polish-heavy extras
5. manual retry wiring from detail

This first cut delivers the product correction the repository most clearly needs: article-stage visibility and retry from the frontend workbench.
