# Reading And Article Processing Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add server-backed pagination to the reading list and article-processing list, add dynamic stage-to-error filtering on article processing, and add article-processing batch retry without changing the current static frontend architecture.

**Architecture:** The backend remains the source of truth for filtering, pagination, dynamic option generation, and retry eligibility. The frontend keeps the existing hash-routed single-page shell, but upgrades list routes to carry filter and pagination state, renders pagination controls, and adds a scoped batch-action model for article-processing cards.

**Tech Stack:** Python, SQLite query helpers, WSGI app routing, vanilla JavaScript, static HTML/CSS, `unittest`

---

### Task 1: Extend Query Models For Pagination And New Filters

**Files:**
- Modify: `src/newspaper_translator/api/queries.py`
- Test: `tests/test_api_queries.py`

- [x] **Step 1: Write failing query-layer tests for reading pagination and new reading filters**

```python
def test_article_card_views_support_pagination_reading_status_and_processing_status(self) -> None:
    self.assertIsNotNone(list_article_card_views)

    with tempfile.TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{pathlib.Path(temp_dir) / 'app.db'}"
        run_pending_migrations(database_url)

        article_ready = self._insert_succeeded_article_with_enrichment(
            database_url=database_url,
            translated_title_zh="标题一",
            summary_zh="摘要一",
        )
        article_partial = self._insert_succeeded_article_with_enrichment(
            database_url=database_url,
            translated_title_zh="标题二",
            summary_zh=None,
            enrichment_status="partial",
        )
        self._insert_succeeded_article_without_enrichment(database_url=database_url)

        page_one, pagination_one = list_article_card_views(
            database_url=database_url,
            page=1,
            page_size=2,
            reading_status="ready",
            processing_status="partial_enrichment",
        )

    self.assertEqual(pagination_one.total_count, 1)
    self.assertEqual(pagination_one.total_pages, 1)
    self.assertEqual(len(page_one), 1)
    self.assertEqual(page_one[0].article_id, article_partial.article_id)
```

- [x] **Step 2: Run the focused query test and verify it fails**

Run:

```bash
python -m unittest tests.test_api_queries.ApiQueryViewTests.test_article_card_views_support_pagination_reading_status_and_processing_status -v
```

Expected: FAIL because `list_article_card_views()` does not yet accept `page`, `page_size`, or `processing_status`, and it does not return pagination metadata.

- [x] **Step 3: Write failing query-layer tests for article-processing pagination and dynamic filter options**

```python
def test_article_processing_card_views_support_pagination_step_and_error_message(self) -> None:
    self.assertIsNotNone(list_article_processing_card_views)

    with tempfile.TemporaryDirectory() as temp_dir:
        database_url = f"sqlite:///{pathlib.Path(temp_dir) / 'app.db'}"
        run_pending_migrations(database_url)

        self._insert_article_processing_run(
            database_url=database_url,
            article_key="article-a",
            status="failed_retryable",
            current_step="enrich",
            last_error_message="summary timeout",
        )
        self._insert_article_processing_run(
            database_url=database_url,
            article_key="article-b",
            status="failed_retryable",
            current_step="translate",
            last_error_message="quota exhausted",
        )

        runs, pagination = list_article_processing_card_views(
            database_url=database_url,
            page=1,
            page_size=10,
            status="failed_retryable",
            step="enrich",
            error_message="summary timeout",
        )

    self.assertEqual(pagination.total_count, 1)
    self.assertEqual([run.article_key for run in runs], ["article-a"])

def test_article_processing_filter_options_follow_active_filters(self) -> None:
    options = get_article_processing_filter_options_view(
        database_url=database_url,
        status="failed_retryable",
        source="WSJ",
        step="enrich",
    )

    self.assertEqual(options.steps, ["enrich", "translate"])
    self.assertEqual(options.error_messages, ["summary timeout"])
```

- [x] **Step 4: Run the focused article-processing query tests and verify they fail**

Run:

```bash
python -m unittest \
  tests.test_api_queries.ApiQueryViewTests.test_article_processing_card_views_support_pagination_step_and_error_message \
  tests.test_api_queries.ApiQueryViewTests.test_article_processing_filter_options_follow_active_filters -v
```

Expected: FAIL because the query layer does not yet support `page`, `page_size`, `step`, `error_message`, or dynamic filter-option shaping.

- [x] **Step 5: Implement minimal query-layer changes**

```python
@dataclass(frozen=True)
class PaginationView:
    page: int
    page_size: int
    total_count: int
    total_pages: int


def list_article_card_views(
    *,
    database_url: str,
    source: str | None = None,
    tag: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    reading_status: str | None = None,
    processing_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ArticleCardView], PaginationView]:
    ...


def list_article_processing_card_views(
    *,
    database_url: str,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
) -> tuple[list[ArticleProcessingCardView], PaginationView]:
    ...


def get_article_processing_filter_options_view(
    *,
    database_url: str,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
) -> ArticleProcessingFilterOptionsView:
    ...
```

- [x] **Step 6: Run the focused query tests and verify they pass**

Run:

```bash
python -m unittest \
  tests.test_api_queries.ApiQueryViewTests.test_article_card_views_support_pagination_reading_status_and_processing_status \
  tests.test_api_queries.ApiQueryViewTests.test_article_processing_card_views_support_pagination_step_and_error_message \
  tests.test_api_queries.ApiQueryViewTests.test_article_processing_filter_options_follow_active_filters -v
```

Expected: PASS

- [x] **Step 7: Commit the query-layer slice**

```bash
git add src/newspaper_translator/api/queries.py tests/test_api_queries.py
git commit -m "feat: add paginated article and processing queries"
```

### Task 2: Expose New API Endpoints And Batch Retry Operations

**Files:**
- Modify: `src/newspaper_translator/web.py`
- Modify: `src/newspaper_translator/document_processing.py`
- Test: `tests/test_web.py`

- [x] **Step 1: Write failing web tests for paginated list responses and filter-options endpoint**

```python
def test_api_articles_endpoint_returns_articles_and_pagination(self) -> None:
    status, _, body = _perform_wsgi_request(
        app,
        path="/api/articles",
        query_string="page=2&page_size=1&reading_status=ready",
    )

    payload = json.loads(body.decode("utf-8"))

    self.assertEqual(status, "200 OK")
    self.assertIn("articles", payload)
    self.assertEqual(payload["pagination"]["page"], 2)
    self.assertEqual(payload["pagination"]["page_size"], 1)

def test_article_processing_filter_options_endpoint_returns_dynamic_values(self) -> None:
    status, _, body = _perform_wsgi_request(
        app,
        path="/api/article-processing/filter-options",
        query_string="status=failed_retryable&step=enrich",
    )

    payload = json.loads(body.decode("utf-8"))

    self.assertEqual(status, "200 OK")
    self.assertEqual(payload["steps"], ["enrich", "translate"])
    self.assertEqual(payload["error_messages"], ["summary timeout"])
```

- [x] **Step 2: Run the focused web tests and verify they fail**

Run:

```bash
python -m unittest \
  tests.test_web.WebApiEndpointTests.test_api_articles_endpoint_returns_articles_and_pagination \
  tests.test_web.WebApiEndpointTests.test_article_processing_filter_options_endpoint_returns_dynamic_values -v
```

Expected: FAIL because the endpoints do not yet emit `pagination` and `/api/article-processing/filter-options` does not exist.

- [x] **Step 3: Write failing web tests for article-processing batch retry**

```python
def test_article_processing_retry_batch_selection_mode_updates_only_retryable_rows(self) -> None:
    status, _, body = _perform_wsgi_request(
        app,
        path="/api/article-processing/retry-batch",
        method="POST",
        body=json.dumps(
            {
                "mode": "selection",
                "article_keys": ["retryable-a", "running-b"],
            }
        ).encode("utf-8"),
        content_type="application/json",
    )

    payload = json.loads(body.decode("utf-8"))

    self.assertEqual(status, "200 OK")
    self.assertEqual(payload["matched_count"], 2)
    self.assertEqual(payload["updated_count"], 1)
    self.assertEqual(payload["skipped_count"], 1)

def test_article_processing_retry_batch_filtered_mode_uses_full_filtered_result_set(self) -> None:
    status, _, body = _perform_wsgi_request(
        app,
        path="/api/article-processing/retry-batch",
        method="POST",
        body=json.dumps(
            {
                "mode": "filtered",
                "filters": {
                    "status": "failed_retryable",
                    "source": "WSJ",
                    "step": "enrich",
                    "error_message": "summary timeout",
                },
            }
        ).encode("utf-8"),
        content_type="application/json",
    )

    payload = json.loads(body.decode("utf-8"))

    self.assertEqual(status, "200 OK")
    self.assertGreaterEqual(payload["updated_count"], 1)
```

- [x] **Step 4: Run the batch-retry web tests and verify they fail**

Run:

```bash
python -m unittest \
  tests.test_web.WebApiEndpointTests.test_article_processing_retry_batch_selection_mode_updates_only_retryable_rows \
  tests.test_web.WebApiEndpointTests.test_article_processing_retry_batch_filtered_mode_uses_full_filtered_result_set -v
```

Expected: FAIL because `/api/article-processing/retry-batch` does not exist and there is no batch retry helper yet.

- [x] **Step 5: Implement minimal WSGI and retry-service changes**

```python
def retry_article_processing_runs(
    *,
    database_url: str,
    article_keys: list[str] | None = None,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
) -> BatchRetrySummary:
    ...


if path == "/api/article-processing/filter-options":
    payload = _to_jsonable(
        get_article_processing_filter_options_view(
            database_url=database_url,
            status=_query_value(query, "status"),
            source=_query_value(query, "source"),
            publication_date_from=_query_value(query, "publication_date_from"),
            publication_date_to=_query_value(query, "publication_date_to"),
            step=_query_value(query, "step"),
        )
    )
    return _json_response(start_response, "200 OK", payload)

if path == "/api/article-processing/retry-batch":
    request = _read_json_request(environ)
    summary = retry_article_processing_runs(...)
    return _json_response(start_response, "200 OK", _to_jsonable(summary))
```

- [x] **Step 6: Run the focused web tests and verify they pass**

Run:

```bash
python -m unittest \
  tests.test_web.WebApiEndpointTests.test_api_articles_endpoint_returns_articles_and_pagination \
  tests.test_web.WebApiEndpointTests.test_article_processing_filter_options_endpoint_returns_dynamic_values \
  tests.test_web.WebApiEndpointTests.test_article_processing_retry_batch_selection_mode_updates_only_retryable_rows \
  tests.test_web.WebApiEndpointTests.test_article_processing_retry_batch_filtered_mode_uses_full_filtered_result_set -v
```

Expected: PASS

- [x] **Step 7: Commit the API-surface slice**

```bash
git add src/newspaper_translator/web.py src/newspaper_translator/document_processing.py tests/test_web.py
git commit -m "feat: add paginated article APIs and batch retry endpoint"
```

### Task 3: Add Reading And Article-Processing Controls To The Static Frontend

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_static.py`

- [x] **Step 1: Write failing static tests for new reading and article-processing controls**

```python
def test_frontend_index_defines_pagination_and_batch_retry_controls(self) -> None:
    index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()

    self.assertIn('id="reading-status-filter"', index_text)
    self.assertIn('id="processing-status-filter"', index_text)
    self.assertIn('id="all-articles-pagination"', index_text)
    self.assertIn('id="article-processing-step-filter"', index_text)
    self.assertIn('id="article-processing-error-filter"', index_text)
    self.assertIn('id="article-processing-batch-bar"', index_text)
    self.assertIn('id="article-processing-retry-selected-button"', index_text)
    self.assertIn('id="article-processing-retry-filtered-button"', index_text)
```

- [x] **Step 2: Run the static test and verify it fails**

Run:

```bash
python -m unittest tests.test_frontend_static.FrontendStaticTests.test_frontend_index_defines_pagination_and_batch_retry_controls -v
```

Expected: FAIL because those IDs do not yet exist.

- [x] **Step 3: Add the minimal HTML and CSS hooks**

```html
<label>
  <span>阅读状态</span>
  <select id="reading-status-filter" name="reading_status">
    <option value="">全部状态</option>
    <option value="ready">ready</option>
    <option value="english_fallback">english_fallback</option>
  </select>
</label>

<div id="all-articles-pagination" class="pagination-bar"></div>

<label>
  <span>阶段</span>
  <select id="article-processing-step-filter" name="article_processing_step">
    <option value="">全部阶段</option>
  </select>
</label>
<label>
  <span>错误原因</span>
  <select id="article-processing-error-filter" name="article_processing_error">
    <option value="">先选择阶段</option>
  </select>
</label>

<div id="article-processing-batch-bar" class="batch-action-bar hidden"></div>
```

```css
.pagination-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.batch-action-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}
```

- [x] **Step 4: Run the static tests and verify they pass**

Run:

```bash
python -m unittest tests.test_frontend_static -v
```

Expected: PASS

- [x] **Step 5: Commit the markup and style slice**

```bash
git add frontend/index.html frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: add frontend pagination and batch action controls"
```

### Task 4: Wire Frontend Route State, Pagination, And Dynamic Filter Options

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/test_frontend_static.py`

- [x] **Step 1: Write failing static assertions for the new frontend wiring**

```python
def test_frontend_app_requests_pagination_filter_and_batch_retry_surfaces(self) -> None:
    app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()

    self.assertIn("/api/article-processing/filter-options", app_text)
    self.assertIn("/api/article-processing/retry-batch", app_text)
    self.assertIn("reading-status-filter", app_text)
    self.assertIn("processing-status-filter", app_text)
    self.assertIn("article-processing-step-filter", app_text)
    self.assertIn("article-processing-error-filter", app_text)
    self.assertIn("page_size", app_text)
    self.assertIn("URLSearchParams", app_text)
```

- [x] **Step 2: Run the focused static assertion and verify it fails**

Run:

```bash
python -m unittest tests.test_frontend_static.FrontendStaticTests.test_frontend_app_requests_pagination_filter_and_batch_retry_surfaces -v
```

Expected: FAIL because the frontend does not yet call the new endpoints or carry page state.

- [x] **Step 3: Implement the route-state and fetch wiring**

```javascript
function getRouteQueryParams() {
  const hash = window.location.hash.replace(/^#/, "");
  const [routeName, rawQuery = ""] = hash.split("?");
  return { routeName, params: new URLSearchParams(rawQuery) };
}

function renderPagination(container, pagination, onPageChange) {
  container.replaceChildren();
  // previous, page label, next
}

async function loadArticleProcessingFilterOptions() {
  const queryString = buildArticleProcessingFilterOptionsQueryString();
  const payload = await fetchJson(
    queryString
      ? `/api/article-processing/filter-options?${queryString}`
      : "/api/article-processing/filter-options"
  );
  renderSelectOptions(articleProcessingStepFilter, payload.steps, "全部阶段");
  renderDependentErrorOptions(payload.error_messages);
}

async function requestBatchArticleRetry(body) {
  return fetchJson("/api/article-processing/retry-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
```

- [x] **Step 4: Run all frontend static tests and verify they pass**

Run:

```bash
python -m unittest tests.test_frontend_static -v
```

Expected: PASS

- [x] **Step 5: Commit the frontend wiring slice**

```bash
git add frontend/app.js tests/test_frontend_static.py
git commit -m "feat: wire frontend pagination and dynamic processing filters"
```

### Task 5: Implement Batch Selection Behavior And End-To-End Frontend Flow

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Test: `tests/test_frontend_static.py`

- [x] **Step 1: Add failing static coverage for selection and batch-action rendering hooks**

```python
def test_frontend_index_and_app_define_processing_selection_flow(self) -> None:
    index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
    app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()

    self.assertIn('id="article-processing-selection-count"', index_text)
    self.assertIn("selectedArticleProcessingKeys", app_text)
    self.assertIn("requestBatchArticleRetry", app_text)
    self.assertIn("articleProcessingRetryFilteredButton", app_text)
```

- [x] **Step 2: Run the focused static test and verify it fails**

Run:

```bash
python -m unittest tests.test_frontend_static.FrontendStaticTests.test_frontend_index_and_app_define_processing_selection_flow -v
```

Expected: FAIL because the selection state and batch-action hooks do not yet exist.

- [x] **Step 3: Implement minimal selection-state behavior**

```javascript
const selectedArticleProcessingKeys = new Set();

function toggleArticleProcessingSelection(articleKey, checked) {
  if (checked) {
    selectedArticleProcessingKeys.add(articleKey);
  } else {
    selectedArticleProcessingKeys.delete(articleKey);
  }
  renderArticleProcessingBatchBar();
}

async function retrySelectedArticleProcessingRuns() {
  const payload = await requestBatchArticleRetry({
    mode: "selection",
    article_keys: Array.from(selectedArticleProcessingKeys),
  });
  selectedArticleProcessingKeys.clear();
  await loadArticleProcessing();
  setStatus(`批量重试完成：更新 ${payload.updated_count} 条，跳过 ${payload.skipped_count} 条。`);
}

async function retryFilteredArticleProcessingRuns() {
  const payload = await requestBatchArticleRetry({
    mode: "filtered",
    filters: getCurrentArticleProcessingFilters(),
  });
  selectedArticleProcessingKeys.clear();
  await loadArticleProcessing();
  setStatus(`筛选结果批量重试完成：更新 ${payload.updated_count} 条。`);
}
```

- [x] **Step 4: Run the full targeted test suite and verify it passes**

Run:

```bash
python -m unittest \
  tests.test_api_queries \
  tests.test_web \
  tests.test_frontend_static -v
```

Expected: PASS

- [x] **Step 5: Commit the batch-selection slice**

```bash
git add frontend/app.js frontend/index.html frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: add article processing batch retry controls"
```

### Task 6: Final Regression Pass And Documentation Sanity Check

**Files:**
- Modify: `docs/superpowers/specs/2026-05-08-reading-and-article-processing-pagination-design.md` only if implementation reveals a spec mismatch
- Verify: `docs/superpowers/plans/2026-05-08-reading-and-article-processing-pagination-implementation-plan.md`

- [x] **Step 1: Run the full relevant regression suite**

Run:

```bash
python -m unittest \
  tests.test_api_queries \
  tests.test_web \
  tests.test_frontend_static -v
```

Expected: PASS with new pagination, filter-option, and batch-retry coverage included.

- [x] **Step 2: Manually verify the implemented UI flow in the browser**

Run:

```bash
docker compose up frontend web -d
```

Open:

```text
http://127.0.0.1:3000
```

Expected:

- reading list keeps filters while paging
- article-processing step selection enables error-message choices
- article-processing list pages correctly
- retry selected and retry filtered actions both refresh the list and status text

- [x] **Step 3: Check for plan/spec drift and fix only if needed**

```text
Compare the implementation against:
- docs/superpowers/specs/2026-05-08-reading-and-article-processing-pagination-design.md
- docs/superpowers/plans/2026-05-08-reading-and-article-processing-pagination-implementation-plan.md
```

Expected: No drift. If one small mismatch is discovered, update the spec wording in the same commit as the implementation clarification.

- [x] **Step 4: Create the final integration commit**

```bash
git add src/newspaper_translator/api/queries.py \
  src/newspaper_translator/document_processing.py \
  src/newspaper_translator/web.py \
  frontend/index.html \
  frontend/styles.css \
  frontend/app.js \
  tests/test_api_queries.py \
  tests/test_web.py \
  tests/test_frontend_static.py
git commit -m "feat: add paginated reading and article processing workbench"
```

## Self-Review

- Spec coverage:
  - reading pagination is covered in Tasks 1, 2, 3, and 4
  - reading filters for `reading_status` and `processing_status` are covered in Tasks 1, 2, and 4
  - article-processing pagination is covered in Tasks 1, 2, 3, and 4
  - dynamic stage and error-message filtering is covered in Tasks 1, 2, and 4
  - batch retry for selection and full filtered result set is covered in Tasks 2 and 5
  - frontend route-state preservation is covered in Task 4
  - operator feedback and retry eligibility are covered in Tasks 2 and 5
- Placeholder scan:
  - no `TODO`, `TBD`, or “implement later” markers remain
  - each code-changing task includes concrete code snippets, commands, and expected outcomes
- Type consistency:
  - query tasks consistently use `PaginationView`
  - article-processing option tasks consistently use `get_article_processing_filter_options_view`
  - batch retry tasks consistently use `requestBatchArticleRetry()` on the frontend and `retry_article_processing_runs()` on the backend
