# Reading And Article Processing Pagination Design

Date: 2026-05-08

Related documents:

- [Dashboard And Operator Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-29-dashboard-and-operator-workbench-design.md)
- [Article Processing Workbench Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-02-article-processing-workbench-design.md)
- [Article Stage Retry And Identity Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-30-article-stage-retry-design.md)

## Overview

The current frontend exposes two list surfaces with the same structural weakness:

- the reading list has filters but no pagination
- the article-processing list is capped at 50 rows
- the article-processing list cannot filter by failure stage and error message
- the article-processing list only supports single-item manual retry

This design upgrades both list surfaces to server-backed pagination and extends the article-processing workbench with dynamic failure filtering and batch retry. The goal is to make the operator and reading flows usable against a growing daily archive without changing the current static frontend architecture or collapsing reading and troubleshooting into one page.

## Goals

- Add standard pagination to the reading list.
- Keep reading filters while making paged results stable and refreshable.
- Add standard pagination to the article-processing list.
- Remove the hard 50-row ceiling as the effective browsing model.
- Add article-processing filtering by stage and error message.
- Make stage and error-message options dynamic based on current data.
- Add manual batch retry for selected article-processing rows.
- Add manual batch retry for all retryable rows in the current filtered result set.
- Preserve the existing article detail, article-processing detail, and document detail page purposes.

## Non-Goals

- Rebuilding the frontend in a framework.
- Replacing card lists with a data-grid or table product.
- Merging article reading detail and article-processing detail into one page.
- Adding batch retry for document processing in this slice.
- Designing error normalization, error taxonomy, or fuzzy error grouping.
- Changing retry semantics for single-item article retry.

## Product Decisions

- Use standard pagination with page number, previous page, and next page controls.
- Keep pagination and filters in the route state so refresh and deep-link behavior remain stable.
- Keep the current card-list visual model for both reading and article-processing lists.
- Add reading-page filtering for `reading_status` and enrichment-oriented processing status.
- Do not expose article-processing `current_step` or `last_error_message` on the reading page.
- Add article-processing failure filtering as a two-level control:
  - choose stage first
  - choose error message second
- Populate article-processing stage and error-message options dynamically from backend data.
- Support both batch retry modes:
  - retry selected rows
  - retry all retryable rows in the current filtered result set
- Exclude non-retryable rows from actual batch retry updates even if they appear in the filtered result set.

## Reading List Design

### User Experience

The reading page remains the current card-based browsing surface. The left filter panel continues to own reading filters, and the main content continues to render article cards. The functional change is that the list becomes a paged result set instead of an unbounded in-memory set.

The reading list supports these filters:

- `source`
- `tag`
- `publication_date_from`
- `publication_date_to`
- `reading_status`
- `processing_status`

Pagination uses standard controls:

- previous page
- explicit page indicator
- next page

The visible result metadata should show enough context for operators to understand where they are, for example current page, total pages, and total visible articles.

### Filter Semantics

`reading_status` maps to reading-surface readiness and fallback behavior, using the same semantics already implied by the current frontend:

- `ready`
- `english_fallback`

`processing_status` is limited to reading-surface content completeness, not pipeline troubleshooting state. The initial supported value set should be derived from what the reading API can already determine safely, such as:

- fully enriched content
- partial enrichment content

This keeps reading filters useful without leaking article-processing internals into a reader-facing list.

### Pagination Behavior

Pagination must preserve the current filter set during page changes.

If the user changes any filter:

- the list resets to page 1
- the route is updated to the new filter state
- the backend recomputes total count and total pages

If a previously valid page becomes out of range after filtering, the frontend should automatically return to page 1 rather than displaying an empty page that looks like a data failure.

## Article-Processing List Design

### User Experience

The article-processing list remains a card-based operator surface. The current detail page remains separate and is still opened by clicking an item.

The list gains:

- standard pagination
- checkbox selection per row
- a batch action bar
- stage filter
- error-message filter

The metadata area should report current page and total matching rows so an operator can tell whether a filter narrowed the result set or merely changed the visible page.

### Stage And Error-Message Filtering

The filter sequence is intentionally hierarchical:

1. the operator chooses an article-processing stage
2. the frontend then offers error-message values that exist under that stage in the current filtered data set

`error_message` stays disabled until a stage is chosen. This prevents presenting an oversized flat list of unrelated messages and avoids cross-stage ambiguity when the same message appears in different pipeline steps.

The option set is dynamic and context-sensitive. The available stage list and available error-message list should honor the rest of the active filters, including:

- article-processing status
- source
- publication date range

If the operator changes a filter and the current stage or error-message value is no longer valid, the frontend should clear the now-invalid value rather than silently sending a stale filter.

### Pagination Behavior

The article-processing page uses the same standard pagination model as the reading list:

- page number
- previous page
- next page

Changing any filter resets the list to page 1. Clicking into detail and returning to the list should preserve the filter and page state in the route.

## Batch Retry Design

### Supported Modes

The article-processing workbench supports two manual batch retry modes:

1. retry selected rows
2. retry all retryable rows in the current filtered result set

The second mode is defined against the full filtered result set, not just the current page. This is important because pagination is a browsing tool, not a hidden action boundary.

### Eligibility Rules

Batch retry should only modify rows that are truly retryable. The approved behavior in this slice is:

- include `failed_retryable`
- exclude `pending`
- exclude `running`
- exclude `manual_retry_requested`
- exclude `failed_terminal`
- exclude `succeeded`

Excluding `manual_retry_requested` avoids repeated operator actions that do not materially change queue state.

### Operator Feedback

Batch retry should not behave like a silent bulk write. The backend response should tell the frontend:

- how many rows matched the requested scope
- how many rows were updated
- how many rows were skipped as non-retryable

The frontend should surface that result in status messaging and then refresh the current article-processing list.

### Selection Model

Each article-processing card gets a checkbox. The page-level action bar should provide:

- selected row count
- retry selected rows
- retry all retryable rows in current filtered result set
- clear selection

Selection is a page interaction state, not a durable server-side object. It does not need to survive a full route change away from the page, but it should survive simple UI interactions within the page until the operator clears it or the list is refreshed after a batch action.

## API Design

### Reading List Endpoint

`GET /api/articles` should add these query parameters:

- `page`
- `page_size`
- `reading_status`
- `processing_status`

The response should preserve the existing top-level `articles` key and add a `pagination` object instead of replacing the payload shape entirely. That keeps the change backward-compatible for current frontend expectations while still making pagination explicit.

Recommended response shape:

```json
{
  "articles": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_count": 153,
    "total_pages": 8
  }
}
```

### Article-Processing List Endpoint

`GET /api/article-processing` should add these query parameters:

- `page`
- `page_size`
- `step`
- `error_message`

It should preserve the existing top-level `runs` key and add the same `pagination` object shape.

Recommended response shape:

```json
{
  "runs": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_count": 81,
    "total_pages": 5
  }
}
```

### Article-Processing Filter Options Endpoint

The article-processing page needs backend-provided dynamic filter options for stage and error message. Add a dedicated endpoint for that purpose instead of overloading the list response with bulky option metadata on every request.

Recommended endpoint:

- `GET /api/article-processing/filter-options`

It should accept the current non-dependent filters:

- `status`
- `source`
- `publication_date_from`
- `publication_date_to`
- optional `step`

Behavior:

- without `step`, return all available stage values for the current filter context
- with `step`, also return all available error-message values under that stage and filter context

Recommended response shape:

```json
{
  "steps": ["translate", "enrich"],
  "error_messages": ["summary timeout", "quota exhausted"]
}
```

`error_messages` may be empty when no stage is selected.

### Batch Retry Endpoint

Add a dedicated batch retry endpoint:

- `POST /api/article-processing/retry-batch`

Supported request modes:

- selected-row mode
- filtered-result mode

Recommended request shapes:

```json
{
  "mode": "selection",
  "article_keys": ["article-1", "article-2"]
}
```

```json
{
  "mode": "filtered",
  "filters": {
    "status": "failed_retryable",
    "source": "WSJ",
    "publication_date_from": "2026-05-01",
    "publication_date_to": "2026-05-08",
    "step": "enrich",
    "error_message": "summary timeout"
  }
}
```

Recommended response shape:

```json
{
  "matched_count": 24,
  "updated_count": 19,
  "skipped_count": 5
}
```

## Query And Persistence Design

### Reading List Queries

The reading query layer should gain:

- total-count query
- `LIMIT` and `OFFSET`
- reading-status filtering
- enrichment-oriented processing-status filtering

Sorting should remain stable and deterministic so pagination does not duplicate or skip rows across adjacent pages under a fixed filter set.

### Article-Processing Queries

The article-processing query layer should gain:

- total-count query
- `LIMIT` and `OFFSET`
- stage filtering by `current_step`
- exact-match filtering by `last_error_message`

`error_message` should use the stored raw `last_error_message` value as the filter token. This slice deliberately does not introduce normalization or fuzzy grouping because the system does not yet have a stable error taxonomy.

### Dynamic Filter Option Queries

The article-processing filter-option query path should:

- compute distinct `current_step` values in the active filter context
- compute distinct `last_error_message` values for the selected step in the active filter context

These queries should exclude null or empty error messages from the error-message option list.

### Retry Writes

The batch retry write path should reuse existing manual retry semantics at the row level. The slice should not invent a second retry state model. Operationally, that means qualifying rows are moved to `manual_retry_requested` the same way a single-item retry already behaves.

## Frontend State And Routing

The frontend should route reading-list state and article-processing-list state explicitly rather than keeping page number only in memory. This includes:

- current page
- page size
- current filters

The project already uses hash-based routing. The new pagination and filter state should stay within that routing model so refresh and back-navigation remain consistent with the current app structure.

The detail routes should continue to work as they do today:

- reading detail remains `#article/<article_id>`
- article-processing detail remains `#article-processing/<article_key>`

Returning from detail to list should restore the paged list state rather than rebuilding from default filters.

## Error Handling

- Invalid `page` or `page_size` input should be normalized to safe defaults.
- Requesting a page beyond `total_pages` should not produce a server error.
- If a selected batch-retry payload contains unknown `article_keys`, they should simply count as unmatched.
- If a filtered batch-retry request matches zero retryable rows, the endpoint should return a successful zero-update summary rather than failing.
- Dynamic filter-option endpoints should return empty arrays when the current filter context has no matching stages or messages.

## Testing Plan

Tests should cover:

- reading-list pagination count, page slicing, and deterministic ordering
- reading-list filtering by `reading_status`
- reading-list filtering by enrichment-oriented `processing_status`
- article-processing pagination count, page slicing, and deterministic ordering
- article-processing filtering by `status`, `source`, `date`, `step`, and `error_message`
- dynamic stage-option generation in filtered contexts
- dynamic error-message option generation under a selected stage
- batch retry in selection mode
- batch retry in filtered-result mode
- batch retry skipping non-retryable rows while reporting counts
- web API response shape compatibility for existing `articles` and `runs` keys
- frontend static coverage for:
  - pagination controls
  - reading filters for readiness/completeness
  - article-processing step and error-message controls
  - selection checkboxes
  - batch action bar wiring

## Implementation Notes

*Recorded 2026-05-08 after implementation.*

**Minor deviations from spec accepted during implementation:**

- `error_message` filter shows placeholder text "先选择阶段" when no stage is selected instead of being HTML-`disabled`. Functional behavior is equivalent.
- The batch action bar does not have a standalone "clear selection" button. Selection is cleared automatically after each batch retry action, which covers the primary operator workflow without adding a redundant control.

**Post-implementation corrections:**

- Batch retry eligibility was extended to include `failed_terminal` in addition to `failed_retryable`. The spec originally excluded `failed_terminal` from batch retry, but operator feedback clarified that terminal failures are precisely the articles that need manual intervention, whereas `failed_retryable` rows are retried automatically by the worker. Both the Python eligibility filter and the SQL `UPDATE` WHERE clause were updated accordingly, and the frontend now renders checkboxes on both statuses.
- Fixed a bug where `fetchJson` did not forward `options.body` to the underlying `fetch` call. All POST requests sent via `fetchJson` (including retry-batch) were arriving at the backend with an empty body, causing consistent 400 responses. Added `body: options.body` to the fetch options object.

## Rollout Notes

The implementation should default both paged lists to a modest page size such as 20. The exact default can be finalized during implementation, but both surfaces should use the same default unless a strong operator workflow reason emerges to diverge.

This slice should be implemented without broadening scope into document-processing pagination. However, the pagination response model and frontend utility code should be written so the document-processing list can adopt the same pattern later without redesign.
