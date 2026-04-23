# Gmail Import Audit Design

Date: 2026-04-23

## Overview

This slice adds durable auditability to the existing Gmail import flow.

The system should record:

- one import run record for each `gmail-import` execution
- one import item record for each processed message, attachment, and body link
- success, skipped, and failed outcomes for every item
- summary counts that make recent runs easy to inspect from the CLI and a minimal web API

This design intentionally keeps Gmail fetch/import logic separate from audit persistence and query logic.

## Architecture

The implementation should use a dedicated import-audit layer rather than growing `gmail.py` further.

Responsibilities:

- `gmail.py`
  Coordinates Gmail config loading, Gmail API access, message parsing, and document import orchestration.
- `import_audit.py`
  Owns import-run creation, item recording, run finalization, and query helpers for recent runs and items.
- `manage.py`
  Exposes read-only commands for recent runs and run items.
- `web.py`
  Exposes read-only JSON endpoints for recent runs and run items.

## Data Model

Two new tables should be added.

### `import_runs`

One row per `gmail-import` execution.

Suggested fields:

- `run_id`
- `source_name`
- `status`
- `started_at`
- `finished_at`
- `query`
- `allowed_senders_json`
- `max_results`
- `fetched_message_count`
- `imported_attachment_count`
- `created_document_count`
- `skipped_document_count`
- `failed_item_count`
- `skipped_item_count`

Run statuses:

- `running`
- `succeeded`
- `partial`
- `failed`

### `import_run_items`

One row per processed message, attachment, or body link.

Suggested fields:

- `id`
- `run_id`
- `item_type`
- `item_key`
- `message_id`
- `attachment_id`
- `link_url`
- `status`
- `detail_code`
- `detail_message`
- `document_key`
- `created_at`

Item types:

- `message`
- `attachment`
- `body_link`

Item statuses:

- `succeeded`
- `skipped`
- `failed`

## Runtime Semantics

The import flow should be resilient at the item level.

Rules:

- create an `import_runs` row before fetching messages
- if top-level Gmail access fails, mark the run as `failed`
- if a single message, attachment, or body link fails, record the item failure and continue
- if the run completes with any failed items, mark the run as `partial`
- if the run completes without failed items, mark the run as `succeeded`

This keeps the current "best effort" Gmail import behavior while making failures visible and queryable.

## Query Surfaces

### Management commands

Add read-only commands for:

- recent import runs
- run details by `run_id`
- import items, optionally filtered by `status` and `item_type`

### Web API

Add read-only JSON endpoints for:

- `GET /import-runs`
- `GET /import-runs/<run_id>`
- `GET /import-runs/<run_id>/items`
- `GET /import-items`

The API should stay minimal and return raw operational data rather than dashboard-specific projections.

## Testing Strategy

This slice should be implemented with TDD in small steps:

1. migration coverage for the new tables
2. repository tests for creating/finalizing runs and querying items
3. Gmail integration coverage for run/item audit recording
4. management command coverage for listing runs and items
5. web API coverage for read-only run/item endpoints
