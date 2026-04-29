# Dashboard And Operator Workbench Implementation Plan

Date: 2026-04-29

Related documents:

- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)
- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)
- [Newspaper Translator Progress Summary](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/status/2026-04-29-progress-summary.md)

## Goal

This plan turns the approved dashboard-and-operator-workbench design into a staged delivery order that reaches a usable local product on top of the existing backend pipeline:

- a reading-first dashboard for processed newspaper articles
- an article detail page with Chinese-first and bilingual reading modes
- a lightweight operator view for document processing state and retry
- a separate frontend layer packaged together with the Python backend and worker in Docker

## Execution Status

Status on 2026-04-29: planning approved, implementation not started yet.

The repository already provides the backend pipeline foundations this product depends on:

- Gmail import with audit history and retry
- MinerU-backed parse and article persistence
- article enrichment persistence and latest-visible rules
- automatic document-level processing through the worker and scheduler
- backend-only web surfaces for import and document-processing status

The main remaining gaps are now product-facing rather than pipeline-facing:

- UI-ready aggregated article and document query models
- a stable API surface for reading and operator pages
- a standalone frontend application
- Docker packaging for the new frontend layer

## Current Starting Point

The repository is in a favorable state for this product slice:

- the backend already knows how to create and update article, enrichment, and document-processing state
- the worker already owns retry semantics and current-state transitions
- version-selection rules for parse and enrichment already exist
- there is no need to redesign the automatic pipeline before starting the dashboard

The current limitations are:

- the existing `web.py` surface is too thin and too low-level for the planned UI
- query logic is still shaped around storage tables rather than UI view models
- there is no dedicated frontend application yet
- operator actions exist, but they are not exposed through a user-friendly reading and operations interface

## Delivery Principles

Implementation should follow these principles:

1. Query layer before page polish.
   The frontend should not start by reverse-engineering raw storage tables.

2. Reading flow before operator expansion.
   The dashboard and article detail pages should land before broader operational refinements.

3. Backend remains the source of truth.
   The frontend should not decide version-selection, degradation, or retry semantics.

4. Each slice must leave a testable increment.
   Every slice should end in something that can be run, queried, or rendered.

5. Container integration is a real slice, not a cleanup task.
   Docker wiring should be treated as first-class work rather than deferred until the end.

## Recommended Delivery Order

### Slice 1: Aggregated Query Foundations

Build the backend query and serialization layer that exposes UI-ready article and document shapes.

Scope:

- add overview aggregation queries
- add article-list aggregation queries
- add article-detail aggregation queries
- add filter-option queries
- add document-processing list and detail aggregation queries
- add serializer helpers for `ArticleCardView`, `ArticleDetailView`, `DocumentProcessingListItemView`, and `DocumentProcessingDetailView`
- encode degradation rules for missing enrichment and stale visible versions

Why first:

- every later API and frontend slice depends on stable query semantics
- this prevents UI logic from leaking into page components

Exit criteria:

- one dashboard article feed can be returned as a UI-ready list
- one article detail payload can be returned without exposing raw run internals
- one document-processing list payload can be returned with current status, step, and retryability
- backend tests cover latest-visible selection and graceful degradation behavior

### Slice 2: Reading API Surface

Expose the query foundations through stable JSON endpoints for the dashboard and article detail flow.

Scope:

- add `GET /api/overview`
- add `GET /api/articles`
- add `GET /api/articles/:article_id`
- add `GET /api/filters`
- add `GET /api/focus-tags/articles`
- add any shared response-shaping helpers needed for pagination or filter metadata

Why second:

- it gives the frontend a stable contract before page implementation grows
- it isolates backend API semantics from frontend component work

Exit criteria:

- the frontend can load top summary data, filter options, article feeds, and article details from stable endpoints
- endpoint tests cover expected query parameters and response shapes

### Slice 3: Frontend Foundation And Dashboard MVP

Create the standalone frontend application and land the first reading page.

Scope:

- scaffold the `frontend/` application
- configure routing, API client setup, and development proxy
- build the base app shell
- implement dashboard summary bar
- implement filter bar
- implement focus-tag section
- implement article cards and all-articles feed
- implement loading, empty, and lightweight hint states

Why third:

- once the reading APIs exist, the dashboard can land as the first user-visible product increment
- it turns backend progress into something immediately usable

Exit criteria:

- a user can open the dashboard and browse processed articles
- filters update the displayed article feed correctly
- focus-tag content is visible and uses the same underlying article model

### Slice 4: Article Detail MVP

Complete the primary reading workflow from list to detail.

Scope:

- add article detail route
- implement metadata rail
- implement Chinese, English, and compare reading modes
- implement optional hero-image rendering
- support returning to current dashboard context
- add a jump from article detail to source document detail

Why fourth:

- the reading product is incomplete until the detail page exists
- it is the smallest next step after the dashboard that creates a full browse-and-read loop

Exit criteria:

- a user can open one article and read it in Chinese, English, or compare mode
- missing enrichment degrades cleanly to English-only display
- the detail page preserves metadata while language mode changes

### Slice 5: Operator API And Views

Expose the existing document-processing control plane through a usable operator interface.

Scope:

- add `GET /api/document-processing`
- add `GET /api/document-processing/:document_key`
- standardize `POST /api/document-processing/:document_key/retry`
- implement document-processing list page
- implement document detail page
- implement retry action and post-action refresh behavior

Why fifth:

- the reading product should already be usable before spending more time on operations views
- the operator surface can now reuse the established frontend foundation

Exit criteria:

- an operator can list document-processing runs by status
- an operator can inspect one document's current state and history summary
- an operator can request retry and see the updated state reflected in the UI

### Slice 6: Shared Polish And Product Integration

Tighten shared UX, navigation, and error presentation across reading and operator pages.

Scope:

- unify badge styles for quality and processing signals
- refine navigation between dashboard, article detail, and document detail
- ensure reading-first ordering survives when status information is present
- add basic not-found and request-error screens
- verify that list/detail pages behave reasonably with empty data or missing enrichment

Why sixth:

- this keeps polish work focused after the core flows exist
- it reduces the risk of fragmented page behavior across the product

Exit criteria:

- primary navigation paths feel coherent
- quality flags and processing badges are visually and conceptually distinct
- empty and degraded states are explicit and readable

### Slice 7: Containerized Deployment Integration

Package the frontend into the existing local product deployment.

Scope:

- add frontend Dockerfile
- update `docker-compose.yml`
- configure frontend-to-API runtime base URL behavior
- verify shared runtime assumptions around storage and article asset URLs
- update README startup instructions for the full product

Why seventh:

- the product is not complete until it runs as one local Docker deployment
- integration issues are easier to diagnose after the core product flows already exist

Exit criteria:

- frontend, API, and worker run together in Docker
- the dashboard is reachable and the API calls resolve correctly inside the composed environment
- README documents the end-to-end startup and usage flow

## Parallel Work Strategy

Some workstreams can run in parallel once earlier blocking slices are complete.

### After Slice 1 begins

Parallelizable work:

- backend query helpers for article views
- backend query helpers for document-processing views

Constraint:

- both lanes must align on shared serializer shapes before API work begins

### After Slice 2 completes

Parallelizable work:

- frontend dashboard page
- frontend article detail page shell
- frontend design system primitives such as badges, cards, and filter components

Constraint:

- the frontend should stub only against approved API contracts, not raw database assumptions

### After Slice 3 completes

Parallelizable work:

- article detail implementation
- operator page implementation

Constraint:

- retry mutation behavior should wait for the operator API contract to stabilize

## Recommended Workstreams

### Workstream 1: Backend Query Layer

- add article feed aggregation
- add article detail aggregation
- add overview aggregation
- add filter-option aggregation
- add document-processing aggregation
- add serializer modules
- add query-layer tests

### Workstream 2: API Layer

- add reading endpoints
- add operator endpoints
- normalize pagination and list response shape
- normalize error response shape where needed
- add endpoint tests

### Workstream 3: Frontend Foundation

- create `frontend/`
- add route structure
- add typed API client layer
- add app shell and navigation
- add reusable card, badge, and filter primitives

### Workstream 4: Reading Experience

- build dashboard summary and filters
- build focus-tag section
- build article feed
- build article detail page
- build language mode switching

### Workstream 5: Operator Experience

- build document-processing list
- build document detail
- build retry action flow
- build operator-oriented error presentation

### Workstream 6: Docker And Runtime Integration

- add frontend image build
- wire compose networking
- configure runtime API origin
- update docs

## Testing Strategy

Each slice should follow the same loop:

1. add one failing test or one missing verification target
2. run the narrowest possible scope and verify RED
3. add the minimum implementation to reach GREEN
4. rerun the targeted verification
5. refactor while staying green

Recommended test focus by slice:

### Slice 1 Tests

- latest-visible article selection for one document
- enrichment fallback to English when no usable Chinese result exists
- article-card serializer returns expected fields
- document-processing serializer returns retryability and current-step correctly

### Slice 2 Tests

- `GET /api/articles` respects filter parameters
- `GET /api/articles/:article_id` returns detail payload
- `GET /api/overview` returns expected summary fields
- `GET /api/filters` returns stable filter metadata

### Slice 3 Tests

- dashboard renders summary and article cards
- filter interactions update query state
- focus-tag section renders matching articles
- empty dashboard states render clearly

### Slice 4 Tests

- article detail renders Chinese mode by default
- article detail falls back to English-only mode when enrichment is missing
- compare mode displays both language panes

### Slice 5 Tests

- document-processing list renders status and latest error
- retry action triggers mutation and refresh
- document detail renders current article outputs and processing summary

### Slice 7 Tests

- composed services start successfully
- frontend can resolve API calls in Docker
- README startup flow matches the real deployment behavior

## Sequencing Risks And Controls

### Risk 1: The frontend starts before the article view models settle

Consequence:

- components are built against unstable or backend-shaped payloads

Control:

- do not begin most frontend feature work until Slice 1 and Slice 2 contracts exist

### Risk 2: Operator views expand into a larger admin scope

Consequence:

- reading-path delivery slows down

Control:

- keep V1 operator actions to status inspection and manual retry only

### Risk 3: Missing article display metadata causes UI churn

Consequence:

- repeated redesign around source names, page labels, and badge meanings

Control:

- lock `source_name`, `page_label`, `quality_flags`, and `processing_badges` early in Slice 1

### Risk 4: Docker integration is delayed until the end

Consequence:

- late surprises around asset URLs, service routing, and environment configuration

Control:

- treat containerization as a formal slice with explicit exit criteria

## Success Criteria

We should consider this plan successfully implemented when the repository can:

- serve a dashboard that lists processed article outputs through a separate frontend
- open an article detail page with Chinese-first and bilingual reading support
- show focus-tag-driven content at the top of the reading experience
- expose document-processing status and retry through dedicated operator pages
- run frontend, API, and worker together in Docker as one local product

## What We Are Not Doing Yet

- authentication
- article editing or correction workflows
- advanced admin tooling
- full-text search
- notifications or alerts
- PDF visual review tools
- richer recommendation or ranking logic
