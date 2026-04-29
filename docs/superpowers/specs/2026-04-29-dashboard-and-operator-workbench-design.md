# Dashboard And Operator Workbench Design

Date: 2026-04-29

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [Scheduled Automatic Document Processing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-scheduled-automatic-document-processing-design.md)
- [Newspaper Translator Progress Summary](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/status/2026-04-29-progress-summary.md)

## Overview

This document defines the first product-facing dashboard slice for the repository after Gmail import, MinerU parsing, article persistence, article enrichment, and automatic background processing have already been proven.

The target outcome is a local news workbench that runs in Docker as one integrated product while using a clean frontend/backend split:

- a reading-first dashboard for browsing processed articles
- an article detail view optimized for Chinese-first reading with bilingual fallback
- a lightweight operator surface for document processing status and retry
- a query layer that exposes UI-ready article and document view models instead of raw storage tables

This slice is intentionally product-facing rather than pipeline-facing. It turns the existing backend workflow into a usable reading and operations interface without expanding into editorial tooling, search infrastructure, or full admin features.

## Product Goals

- Provide a daily dashboard for browsing article-level outputs from imported newspaper PDFs
- Prioritize reading experience while preserving enough operator visibility to understand failures and request retry
- Keep the primary unit of browsing as an article rather than a PDF page or parser fragment
- Reuse the repository's current version rules so later failed runs do not hide older usable article outputs
- Support a separate frontend layer without moving workflow logic out of the Python backend
- Package frontend, API, worker, and storage into one Docker-based local deployment

## Product Balance

The first dashboard release should balance two goals:

- reading experience
- operations visibility

Reading experience should still win when tradeoffs appear.

This means:

- the default landing page should surface readable content before process internals
- failure and retry information should remain visible but secondary
- operator workflows should be available through dedicated views instead of dominating the reading interface

## Non-Goals

This slice does not include:

- authentication or permissions
- manual article editing
- manual parse correction tooling
- full-text search infrastructure
- dashboard analytics beyond lightweight summary counts
- advanced notification or alerting workflows
- PDF page-level visual review tooling
- article-level enrichment orchestration redesign

## User Experience

The product has four first-class pages in V1.

### 1. Dashboard Home

This is the main entry point and should absorb most usage time.

The page structure is:

1. top summary bar
2. filter bar
3. focus-tag section
4. all-articles section

The top summary bar shows:

- imported document count for the current day
- newly available article count for the current day
- currently processing document count
- pending exception count

The filter bar supports:

- source filter
- publication date range
- tag filter
- article availability or processing-status filter
- preferred reading language

The focus-tag section shows recently available articles that match the user's configured focus tags while still respecting active filters where appropriate.

The all-articles section shows the current article feed using the same card pattern as the focus-tag section.

### 2. Article Detail

This page is article-centric and optimized for reading rather than system inspection.

The layout is:

- left metadata rail
- right reading area

The metadata rail contains:

- summary
- tags
- source
- publication date
- page label
- quality indicators
- lightweight processing indicators

The reading area contains:

- optional hero image
- title
- language mode switch
- article body

The reading modes are:

- Chinese
- English
- side-by-side comparison

Default mode is Chinese. Side-by-side comparison is an explicit expanded mode rather than the default.

### 3. Document Processing

This page is the operator-oriented list view.

It is organized around documents rather than scheduler runs.

The page supports:

- filtering by processing status
- scanning recent failures quickly
- viewing current step and latest error
- triggering manual retry

This page should remain operationally useful without becoming a generic admin console.

### 4. Document Detail

This page is the bridge between readable article outputs and processing history.

It should show:

- document metadata
- current processing state
- import context
- latest parse and enrichment summary
- current visible articles for the document
- relevant run history for debugging

## Recommended Technical Approach

Use a split frontend/backend architecture packaged into one Docker deployment.

Recommended services:

- `frontend`: a standalone SPA for reading and operator views
- `api`: the Python backend exposing JSON query and mutation endpoints
- `worker`: the existing background scheduler and processing worker
- `db`: the current SQLite database

This is the recommended approach because:

- the reading interface needs richer routing and interaction than the current lightweight Python web layer is suited for
- the current Python backend already owns the business rules and should continue to own query semantics
- Docker deployment remains straightforward even with a separate frontend
- it avoids turning the frontend into a second source of truth for workflow state

## Frontend Technology Choice

Recommended stack:

- React
- Vite
- TypeScript
- React Router
- TanStack Query
- CSS Modules or Tailwind CSS

Why this is the right fit:

- React handles the reading and route transitions cleanly
- Vite keeps the local developer loop fast and the container build simple
- TanStack Query fits list/detail queries plus retry-triggered refreshes
- TypeScript helps stabilize the UI contracts around aggregated backend view models

Not recommended for V1:

- Next.js
- GraphQL
- Redux or other heavy global state layers
- a large admin-oriented component framework

## Backend Architecture

The current backend should evolve from one lightweight endpoint module into a small API surface organized by product concerns.

Recommended backend areas:

### 1. Overview API

Responsibilities:

- top-bar summary counts
- lightweight dashboard-level status snapshot

### 2. Article Query API

Responsibilities:

- home page article feed
- focus-tag article feed
- article detail payload
- filter options payload

### 3. Document Operations API

Responsibilities:

- document processing list
- document processing detail
- manual retry

### 4. Query And Serialization Layer

Responsibilities:

- aggregate raw storage tables into UI-ready view models
- centralize current-version rules
- keep parse, enrichment, and document-processing semantics out of the frontend

The backend should remain the only place that decides:

- which parse run is currently visible
- which enrichment result is currently usable
- whether an article should degrade to English-only display
- whether a document failure should still show previously successful article outputs

## Data Access Principle

The UI must not consume raw storage tables directly.

The repository already persists data by processing layer:

- documents
- import runs and items
- parse runs
- final articles
- enrichment runs and outputs
- document processing runs

These are suitable persistence boundaries but poor UI boundaries.

The API must instead expose aggregated view models shaped for the dashboard.

## Core View Models

### ArticleCardView

Used by dashboard cards.

```json
{
  "article_id": "xxx",
  "document_key": "xxx",
  "source_name": "Financial Times",
  "publication_date": "2026-04-22",
  "page_label": "A3/A5",
  "title_en": "Chipmakers prepare for a new subsidy dispute",
  "title_zh": "芯片制造商准备应对新的补贴争端",
  "summary_zh": "中文摘要",
  "tags": ["AI", "Semiconductors"],
  "hero_image_url": null,
  "reading_status": "ready",
  "quality_flags": ["cross_page_merged"],
  "processing_badges": ["partial_enrichment"]
}
```

Rules:

- cards only expose display-ready fields
- parse-run details stay hidden
- `quality_flags` describe content quality
- `processing_badges` describe processing state

### ArticleDetailView

Used by article detail.

```json
{
  "article_id": "xxx",
  "document_key": "xxx",
  "source_name": "Financial Times",
  "publication_date": "2026-04-22",
  "page_label": "A3/A5",
  "title_en": "Chipmakers prepare for a new subsidy dispute",
  "title_zh": "芯片制造商准备应对新的补贴争端",
  "summary_zh": "中文摘要",
  "tags": ["AI", "Trade"],
  "body_text_en": "English article body",
  "body_text_zh": "中文译文",
  "hero_image_url": null,
  "quality": {
    "confidence": "high",
    "flags": ["cross_page_merged"]
  },
  "processing": {
    "document_status": "succeeded",
    "latest_parse_status": "succeeded",
    "latest_enrichment_status": "succeeded"
  }
}
```

Rules:

- detail pages may expose lightweight processing context
- the page still prioritizes readable fields over run internals

### DocumentProcessingListItemView

Used by the document-processing list page.

```json
{
  "document_key": "xxx",
  "source_name": "Financial Times",
  "original_filename": "ft-2026-04-22.pdf",
  "publication_date": "2026-04-22",
  "status": "failed_retryable",
  "current_step": "enrich",
  "automatic_failure_count": 1,
  "last_error_message": "gemini timeout",
  "last_attempt_started_at": "2026-04-29T02:00:00",
  "last_attempt_finished_at": "2026-04-29T02:10:00",
  "article_count": 12,
  "latest_scheduler_run_id": "scheduler-run-1",
  "manual_retry_allowed": true
}
```

Rules:

- the list must make triage easy
- current step, latest error, and retryability should be immediately visible

### DocumentProcessingDetailView

Used by the document detail page.

```json
{
  "document": {},
  "processing": {},
  "import_run": {},
  "latest_parse_run": {},
  "latest_enrichment_summary": {},
  "articles": [],
  "history": {
    "parse_runs": [],
    "enrichment_runs": []
  }
}
```

Rules:

- this page may include more history than the reading pages
- it exists to support diagnosis and manual intervention

## Query Rules

The following rules should be fixed in V1 to avoid frontend/backend drift.

1. The dashboard article feed only shows records that already have a current visible final article.

2. If a usable enrichment result exists, the dashboard prefers:

- translated title
- Chinese summary
- translated body
- ordered tags

3. If no usable enrichment result exists but a final article exists:

- the article is still visible
- the UI degrades to English title and English body
- the UI shows a lightweight processing hint such as `enhancement pending` or `enhancement unavailable`

4. A later failed parse or enrichment attempt must not hide an older usable article version.

5. The focus-tag section is not a separate stored entity in V1.

Instead it is:

- a configured list of focus tags
- a query-level grouping of articles matching those tags

## UI Fields And Derived Presentation Signals

The UI should standardize the following derived fields even if some are initially computed in query code rather than persisted.

### Source Name

Provide one consistent display name per source.

### Page Label

Provide human-readable labels such as `A3` or `B1/B4` rather than parser-order page indexes.

### Hero Image URL

Define the field now even if many articles do not yet have images.

### Quality Flags

Initial recommended set:

- `cross_page_merged`
- `low_confidence`
- `layout_noise_detected`
- `partial_translation_source`

### Processing Badges

Initial recommended set:

- `processing`
- `partial_enrichment`
- `retryable_failure`
- `stale_visible_version`

Quality signals and processing signals must remain separate concepts.

## V1 API Surface

Recommended endpoints:

### Reading Endpoints

- `GET /api/overview`
- `GET /api/articles`
- `GET /api/articles/:article_id`
- `GET /api/filters`
- `GET /api/focus-tags/articles`

### Operator Endpoints

- `GET /api/document-processing`
- `GET /api/document-processing/:document_key`
- `POST /api/document-processing/:document_key/retry`

### Bridge Endpoint

- `GET /api/documents/:document_key/articles`

### Article List Query Parameters

`GET /api/articles` should support:

- `source`
- `publication_date_from`
- `publication_date_to`
- `tag`
- `focus_only`
- `status`
- `page`
- `page_size`
- `sort`

The focus-tag section may reuse the same query model even if it is exposed through a dedicated endpoint for convenience.

## Page-Level Interaction Design

### Dashboard

Interaction order:

1. summary bar
2. filter bar
3. focus-tag section
4. all-articles feed

Design rules:

- show readable outputs before showing system complexity
- card clicks navigate to article detail
- do not overload cards with secondary actions
- focus-tag sections may collapse or expand
- empty states should remain explicit rather than disappearing silently

Default article sort:

- `publication_date desc`
- stable source and article ordering within the same day

V1 should not introduce recommendation ranking logic.

### Article Detail

The page must support:

- quick understanding through Chinese summary and Chinese reading
- deeper verification through English or bilingual comparison

Interaction rules:

- default to Chinese mode
- allow `Chinese`, `English`, and `Compare` modes
- keep metadata stable while switching body language mode
- omit the hero area completely when no image exists

Useful navigation links:

- return to current dashboard results
- open the source document detail page

### Document Processing Page

The page should optimize for quick triage.

Recommended list columns:

- source
- publication date
- original filename
- current status
- current step
- automatic failure count
- latest error
- latest attempt time
- action

V1 action scope:

- manual retry only

### Document Detail Page

Recommended sections:

- document metadata
- current processing state
- import context
- latest parse summary
- latest enrichment summary
- current visible articles
- relevant processing history

This page is for workflow inspection, not for primary reading.

## Error And Degradation Design

The product should follow the rule:

Prefer graceful reading degradation over hiding content.

### Dashboard Cards

Use lightweight badges rather than heavy alerts.

Examples:

- `enhancement pending`
- `low confidence`
- `cross-page merged`
- `document processing`

### Article Detail

Rules:

- if Chinese enrichment is missing, fall back to English
- if summary is missing, still show the body
- if quality is low, show one lightweight note near the title rather than a blocking warning

### Document Views

Document-oriented pages may show stronger operator signals:

- latest error
- failed step
- retryability
- automatic failure ceiling reached

## Frontend State Management Rules

The frontend is responsible for:

- routing
- filter state
- pagination and sorting state
- reading-language mode
- local refresh after retry

The frontend is not responsible for:

- version-selection rules
- document-processing state transitions
- parse or enrichment history interpretation

The frontend is a presentation layer, not a second business-logic layer.

## Recommended Code Organization

### Backend

Recommended additions:

- `src/newspaper_translator/api/overview.py`
- `src/newspaper_translator/api/articles.py`
- `src/newspaper_translator/api/document_processing.py`
- `src/newspaper_translator/api/queries.py`
- `src/newspaper_translator/api/serializers.py`

### Frontend

Recommended structure:

- `frontend/src/pages/DashboardPage`
- `frontend/src/pages/ArticleDetailPage`
- `frontend/src/pages/DocumentProcessingPage`
- `frontend/src/pages/DocumentDetailPage`
- `frontend/src/components/ArticleCard`
- `frontend/src/components/FilterBar`
- `frontend/src/components/StatusBadge`

## Delivery Strategy

The implementation should be split into five slices that each produce a testable product increment.

### Slice 1: Reading Query Foundation

Goal:

- establish stable data contracts for dashboard and article detail

Scope:

- overview query layer
- article list query layer
- article detail query layer
- filter query layer
- serializers and view models
- backend tests for query semantics and degradation rules

Exit criteria:

- the frontend can load dashboard and article detail data from stable APIs

### Slice 2: Dashboard MVP

Goal:

- deliver a usable reading-first home page

Scope:

- summary bar
- filter bar
- focus-tag section
- article card component
- article feed layout
- loading, empty, and lightweight state hints

Exit criteria:

- a user can browse processed articles from the dashboard

### Slice 3: Article Detail MVP

Goal:

- complete the reading workflow

Scope:

- article detail route
- metadata rail
- Chinese, English, and compare modes
- optional hero image
- link back to dashboard and document detail

Exit criteria:

- a user can read one article end to end with bilingual support

### Slice 4: Operator MVP

Goal:

- deliver minimal diagnosis and retry tooling

Scope:

- document-processing list API
- document-processing detail API
- retry mutation API
- document-processing page
- document detail page

Exit criteria:

- an operator can identify a failed document and request retry

### Slice 5: Containerized Product Integration

Goal:

- package the dashboard into the full local Docker deployment

Scope:

- frontend Dockerfile
- compose integration
- environment variable wiring
- frontend-to-API configuration
- README updates

Exit criteria:

- frontend, API, and worker run together in Docker as one product

## Initial Implementation Plan

This section defines the concrete work breakdown that should be expanded into the follow-up implementation plan.

### Workstream 1: Backend Query Layer

- add overview aggregation queries
- add article list aggregation queries
- add article detail aggregation queries
- add filter-option queries
- add document-processing list and detail aggregation queries
- define serializer functions for the four core view models
- add tests for degradation and current-version rules

### Workstream 2: API Layer

- add `GET /api/overview`
- add `GET /api/articles`
- add `GET /api/articles/:article_id`
- add `GET /api/filters`
- add `GET /api/focus-tags/articles`
- add `GET /api/document-processing`
- add `GET /api/document-processing/:document_key`
- standardize `POST /api/document-processing/:document_key/retry`

### Workstream 3: Frontend Foundation

- create `frontend/` application scaffold
- configure router
- configure API client and request primitives
- configure local development proxy to the Python API
- create base page layout and navigation shell

### Workstream 4: Dashboard Implementation

- implement summary bar
- implement filter bar
- implement focus-tag section
- implement article card
- implement article feed with pagination
- implement lightweight quality and processing badges

### Workstream 5: Article Detail Implementation

- implement article detail page shell
- implement metadata rail
- implement language-mode switch
- implement optional compare mode
- implement hero image display rules
- implement navigation back to dashboard context

### Workstream 6: Operator Views

- implement document-processing list page
- implement status filters
- implement document detail page
- implement retry action and refresh behavior
- implement error display patterns

### Workstream 7: Container And Integration Work

- add frontend Dockerfile
- update docker-compose wiring
- configure API base URL and static deployment behavior
- verify shared runtime assumptions for storage and URLs
- update README with full product startup flow

## Testing Strategy

V1 should include:

- backend unit tests for query helpers and serializers
- backend API tests for endpoint behavior
- frontend component tests for cards, filters, and badges
- frontend page tests for dashboard and article detail rendering
- at least one integration path covering dashboard to article detail to document detail

The goal is not exhaustive browser automation in the first slice. The goal is to protect the API contract and the primary user workflows.

## Containerization Model

The deployment should keep a clean split while shipping as one local product.

Recommended runtime layout:

- `frontend` serves the SPA
- `api` serves JSON endpoints
- `worker` runs scheduled import, parsing, and enrichment
- the database and storage mounts remain shared where needed

The design assumes:

- frontend and API can communicate over internal Docker networking
- the worker shares the same database and document storage roots
- the frontend does not read local files directly

## Risks And Controls

### Risk 1: Raw backend structures leak into the frontend

Consequence:

- the frontend ends up reimplementing version and workflow semantics

Control:

- finish the aggregated query layer before building most pages

### Risk 2: Page metadata is technically present but not user-readable

Consequence:

- source, page, and quality indicators feel inconsistent or confusing

Control:

- standardize `source_name`, `page_label`, `quality_flags`, and `processing_badges` before page polish work

### Risk 3: Frontend scope expands into a large admin platform

Consequence:

- delivery slows and the reading product gets diluted

Control:

- keep V1 to four pages and one operator action

### Risk 4: Docker integration reveals path and asset assumptions late

Consequence:

- late deployment issues around frontend, API, and worker wiring

Control:

- include container integration as an explicit delivery slice rather than a final afterthought

## Decision Summary

The approved V1 direction is:

- a reading-first local dashboard
- a separate frontend layer is allowed and recommended
- Docker packaging remains unified
- reading and operations both matter, with reading slightly prioritized
- the backend remains the source of truth for aggregated article and document state
- the implementation should proceed through a query-first, page-second delivery order
