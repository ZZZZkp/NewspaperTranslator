# 工作台筛选调整与文章内联阅读 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让文章处理页不再显示文档状态筛选行；文档与文章两页新增「失败次数 ≥ 阈值」动态筛选；文章处理详情内通过选项卡内联查看文章正文（复用阅读渲染）。

**Architecture:** 后端新增可选过滤参数 `min_failure_count`（`automatic_failure_count >= N`）与全局最大失败次数 `max_failure_count`，前端据 max 动态生成阈值下拉。文章阅读渲染重构为 `createArticleReader(elements)` 工厂，使同一渲染逻辑既服务独立阅读页，也服务文章处理详情内的内嵌 reader。

**Tech Stack:** Python 3（标准库 sqlite3、WSGI）、原生 JS/HTML/CSS、pytest/unittest。

参考 spec：`docs/superpowers/specs/2026-06-12-workbench-filter-and-inline-article-design.md`

---

## 文件结构

- `src/newspaper_translator/document_processing.py` — `list_document_processing_runs` 加 `min_failure_count`；新增 `get_document_processing_max_failure_count`。
- `src/newspaper_translator/api/queries.py` — 文章处理过滤构造器加 `min_failure_count`；`ArticleProcessingFilterOptionsView` 加 `max_failure_count`。
- `src/newspaper_translator/web.py` — 新增 `_query_optional_int`；三个路由透传 `min_failure_count`、文档列表响应加 `max_failure_count`。
- `frontend/index.html` — 文档筛选 div 加 id；两处失败次数下拉；文章处理详情选项卡 + 内嵌 reader DOM。
- `frontend/app.js` — 显隐切换；失败次数下拉重建；reader 工厂重构 + 内嵌实例。
- `frontend/styles.css` — 选项卡/内嵌 reader 样式。
- `tests/test_document_run_store.py`、`tests/test_api_queries.py`、`tests/test_web.py`、`tests/test_frontend_static.py` — 对应测试。

执行环境：所有 `pytest` 命令在仓库根目录运行，使用项目虚拟环境（`.venv`）。若命令报模块找不到，先 `source .venv/bin/activate`。

---

## Task 1: 后端 — 文档失败次数过滤与最大值

**Files:**
- Modify: `src/newspaper_translator/document_processing.py`（`list_document_processing_runs` 约 710-770；文件尾部新增函数）
- Test: `tests/test_document_run_store.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_document_run_store.py` 顶部 import 区把 `list_document_processing_runs`、`get_document_processing_max_failure_count` 加入从 `newspaper_translator.document_processing` 的导入（与现有 `create_document_processing_run`、`fail_document_processing_run` 同组）。然后在该文件的测试类中追加：

```python
    def test_lists_document_processing_runs_filtered_by_min_failure_count(self) -> None:
        self.assertIsNotNone(list_document_processing_runs)
        self.assertIsNotNone(get_document_processing_max_failure_count)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            create_document_processing_run(database_url=database_url, document_key="doc-zero")
            create_document_processing_run(database_url=database_url, document_key="doc-one")
            create_document_processing_run(database_url=database_url, document_key="doc-two")
            # doc-one: 1 次失败 (failed_retryable)
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-one",
                failed_step="parse_persist",
                error_message="boom",
            )
            # doc-two: 2 次失败 (failed_terminal)
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )

            at_least_one = list_document_processing_runs(
                database_url=database_url,
                limit=50,
                min_failure_count=1,
            )
            at_least_two = list_document_processing_runs(
                database_url=database_url,
                limit=50,
                min_failure_count=2,
            )
            with_status = list_document_processing_runs(
                database_url=database_url,
                limit=50,
                status="failed_retryable",
                min_failure_count=1,
            )

        self.assertEqual({run.document_key for run in at_least_one}, {"doc-one", "doc-two"})
        self.assertEqual({run.document_key for run in at_least_two}, {"doc-two"})
        self.assertEqual({run.document_key for run in with_status}, {"doc-one"})

    def test_document_processing_max_failure_count_returns_global_max(self) -> None:
        self.assertIsNotNone(get_document_processing_max_failure_count)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            self.assertEqual(
                get_document_processing_max_failure_count(database_url=database_url),
                0,
            )

            create_document_processing_run(database_url=database_url, document_key="doc-two")
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )
            fail_document_processing_run(
                database_url=database_url,
                document_key="doc-two",
                failed_step="parse_persist",
                error_message="boom",
            )

            self.assertEqual(
                get_document_processing_max_failure_count(database_url=database_url),
                2,
            )
```

> 注：若 import 区采用 try/except 兜底 `None` 的模式（与文件现有风格一致），新符号也加一行 `get_document_processing_max_failure_count = None` 到 except 分支。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_document_run_store.py -k "min_failure_count or max_failure_count" -v`
Expected: FAIL（`TypeError: list_document_processing_runs() got an unexpected keyword argument 'min_failure_count'` 或 `get_document_processing_max_failure_count is None`）

- [ ] **Step 3: 实现 — 重构 `list_document_processing_runs` 为动态 WHERE**

把 `list_document_processing_runs`（当前 status 有/无两分支）整体替换为：

```python
def list_document_processing_runs(
    *,
    database_url: str,
    limit: int,
    status: str | None = None,
    min_failure_count: int | None = None,
) -> list[DocumentProcessingRun]:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if min_failure_count is not None:
        clauses.append("automatic_failure_count >= ?")
        params.append(min_failure_count)
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                processing_run_id,
                scheduler_run_id,
                document_key,
                status,
                current_step,
                automatic_failure_count,
                last_failure_step,
                last_error_message,
                last_attempt_started_at,
                last_attempt_finished_at,
                locked_by,
                lock_expires_at,
                created_at,
                updated_at
            FROM document_processing_runs
            """
            + where_sql
            + """
            ORDER BY updated_at DESC, created_at DESC, rowid DESC
            LIMIT ?
            """,
            tuple([*params, limit]),
        ).fetchall()
    finally:
        connection.close()

    return [_row_to_document_processing_run(row) for row in rows]
```

- [ ] **Step 4: 实现 — 新增 `get_document_processing_max_failure_count`**

在 `document_processing.py` 中 `list_document_processing_runs` 之后新增：

```python
def get_document_processing_max_failure_count(*, database_url: str) -> int:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(automatic_failure_count), 0)
            FROM document_processing_runs
            """
        ).fetchone()
    finally:
        connection.close()
    return int(row[0])
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_document_run_store.py -k "min_failure_count or max_failure_count" -v`
Expected: PASS

- [ ] **Step 6: 回归 + 提交**

Run: `pytest tests/test_document_run_store.py -q`
Expected: PASS（全部）

```bash
git add src/newspaper_translator/document_processing.py tests/test_document_run_store.py
git commit -m "feat: filter document processing runs by min failure count"
```

---

## Task 2: 后端 — 文章失败次数过滤与最大值字段

**Files:**
- Modify: `src/newspaper_translator/api/queries.py`（`ArticleProcessingFilterOptionsView` 约 99-105；`_build_article_processing_where_clauses` 约 210-239；`list_article_processing_card_views` 重载与实现约 690-825；`get_article_processing_filter_options_view` 约 828-890）
- Test: `tests/test_api_queries.py`

- [ ] **Step 1: 写失败测试**

先扩展现有 helper 让其支持 `automatic_failure_count`。在 `tests/test_api_queries.py` 的 `_insert_article_processing_run` 中，把签名与 INSERT 改为：

```python
    def _insert_article_processing_run(
        self,
        *,
        database_path: pathlib.Path,
        article_key: str,
        article_id: str,
        status: str,
        current_step: str,
        last_error_message: str | None = None,
        automatic_failure_count: int = 0,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO article_processing_runs (
                    article_processing_run_id,
                    article_key,
                    article_id,
                    status,
                    current_step,
                    last_error_message,
                    automatic_failure_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"article-processing-{article_key}",
                    article_key,
                    article_id,
                    status,
                    current_step,
                    last_error_message,
                    automatic_failure_count,
                ),
            )
            connection.commit()
        finally:
            connection.close()
```

然后追加测试（放在 `test_article_processing_card_views_support_source_and_date_filters` 附近，复用同样的 `_insert_document` / `_insert_succeeded_article_with_enrichment` / `_get_article_key` 模式）：

```python
    def test_article_processing_cards_filter_by_min_failure_count(self) -> None:
        self.assertIsNotNone(list_article_processing_card_views)
        self.assertIsNotNone(get_article_processing_filter_options_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key,
                publication_date="2026-04-22",
                title="Only article",
                body_suffix="Body.",
                translated_title_zh="文章",
                summary_zh="摘要",
                translated_body_zh="正文。",
                tags=["A", "B", "C"],
            )
            article_key = self._get_article_key(database_path=database_path, article_id=article_id)
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=article_key,
                article_id=article_id,
                status="failed_terminal",
                current_step="enrich",
                last_error_message="boom",
                automatic_failure_count=2,
            )

            matched = list_article_processing_card_views(
                database_url=database_url,
                min_failure_count=2,
            )
            excluded = list_article_processing_card_views(
                database_url=database_url,
                min_failure_count=3,
            )
            options = get_article_processing_filter_options_view(database_url=database_url)

        self.assertEqual([card.article_key for card in matched], [article_key])
        self.assertEqual(excluded, [])
        self.assertEqual(options.max_failure_count, 2)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_api_queries.py -k "min_failure_count" -v`
Expected: FAIL（`unexpected keyword argument 'min_failure_count'` 或 `ArticleProcessingFilterOptionsView` 无 `max_failure_count`）

- [ ] **Step 3: 实现 — 给 view dataclass 加字段**

在 `queries.py` 的 `ArticleProcessingFilterOptionsView` 中新增字段：

```python
@dataclass(frozen=True)
class ArticleProcessingFilterOptionsView:
    statuses: list[str]
    sources: list[str]
    steps: list[str]
    error_messages: list[str]
    max_failure_count: int
```

- [ ] **Step 4: 实现 — where 构造器加 min_failure_count**

在 `_build_article_processing_where_clauses` 的签名加 `min_failure_count: int | None = None`，并在 `error_message` 分支之后、`return` 之前追加：

```python
    if min_failure_count is not None:
        clauses.append("r.automatic_failure_count >= ?")
        params.append(min_failure_count)
```

- [ ] **Step 5: 实现 — `list_article_processing_card_views` 透传**

两个 `@overload` 签名与真实实现签名，均在 `error_message: str | None = None,` 之后加一行 `min_failure_count: int | None = None,`。实现体里调用 `_build_article_processing_where_clauses(...)` 处加上 `min_failure_count=min_failure_count,`：

```python
        clauses, params = _build_article_processing_where_clauses(
            status=status,
            source=source,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
            step=step,
            error_message=error_message,
            min_failure_count=min_failure_count,
        )
```

- [ ] **Step 6: 实现 — filter-options 透传 + 计算 max**

在 `get_article_processing_filter_options_view` 签名加 `min_failure_count: int | None = None`。它内部对 statuses/sources/steps/error_messages 各自构造 where（每个 fetch_distinct 用一组 clauses）。给**每一组** `_build_article_processing_where_clauses(...)` 调用都补上 `min_failure_count=min_failure_count,`（共 4 处：status_clauses、source_clauses、step_clauses、error_clauses）。然后在 `return ArticleProcessingFilterOptionsView(...)` 前查询全局 max（不带任何筛选）并加入返回：

```python
        max_failure_row = connection.execute(
            """
            SELECT COALESCE(MAX(r.automatic_failure_count), 0)
            FROM article_processing_runs r
            """
        ).fetchone()

        return ArticleProcessingFilterOptionsView(
            statuses=fetch_distinct("r.status", status_clauses, status_params),
            sources=fetch_distinct("d.source_name", source_clauses, source_params),
            steps=fetch_distinct("r.current_step", step_clauses, step_params),
            error_messages=fetch_distinct("r.last_error_message", error_clauses, error_params),
            max_failure_count=int(max_failure_row[0]),
        )
```

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_api_queries.py -k "min_failure_count" -v`
Expected: PASS

- [ ] **Step 8: 回归 + 提交**

Run: `pytest tests/test_api_queries.py -q`
Expected: PASS（全部）

```bash
git add src/newspaper_translator/api/queries.py tests/test_api_queries.py
git commit -m "feat: filter article processing cards by min failure count and expose max"
```

---

## Task 3: 后端 — web.py 路由透传

**Files:**
- Modify: `src/newspaper_translator/web.py`（`/api/document-processing` 约 204-214；`/api/article-processing` 约 216-244；`/api/article-processing/filter-options` 约 244-258；`list_document_processing_runs` import；helper 区约 468-477）
- Test: `tests/test_web.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_web.py` 追加（沿用该文件已有的 app 构造与请求 helper；下面用占位名 `self._get_json(app, path)`，请替换为该文件实际使用的请求方式）：

```python
    def test_document_processing_endpoint_exposes_max_failure_count_and_filters(self) -> None:
        # 复用本文件既有的建库与 app 构造方式 seed：
        #  - 一个 0 失败的 document_processing_run
        #  - 一个 2 失败的 document_processing_run（fail 两次）
        # 然后：
        payload_all = self._get_json(app, "/api/document-processing")
        self.assertEqual(payload_all["max_failure_count"], 2)

        payload_filtered = self._get_json(app, "/api/document-processing?min_failure_count=2")
        keys = {run["document_key"] for run in payload_filtered["runs"]}
        self.assertEqual(keys, {"doc-two"})

    def test_document_processing_endpoint_rejects_invalid_min_failure_count(self) -> None:
        status, payload = self._get_json_with_status(app, "/api/document-processing?min_failure_count=abc")
        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status"], "invalid_query_parameter")

    def test_article_processing_filter_options_includes_max_failure_count(self) -> None:
        payload = self._get_json(app, "/api/article-processing/filter-options")
        self.assertIn("max_failure_count", payload)
```

> 实现者注意：若 `test_web.py` 没有现成的 `_get_json` / `_get_json_with_status`，请按该文件已有测试里调用 WSGI app 的方式改写这三个测试（构造 `environ`、捕获 `start_response` 的 status 与 body）。断言要点不变：文档列表响应含 `max_failure_count`、`min_failure_count` 过滤生效、非法值返回 `400 Bad Request` + `{"status": "invalid_query_parameter"}`、filter-options 含 `max_failure_count`。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_web.py -k "max_failure_count or invalid_min_failure" -v`
Expected: FAIL（响应无 `max_failure_count` / 非法值未返回 400）

- [ ] **Step 3: 实现 — 新增 `_query_optional_int` helper**

在 `web.py` 的 `_query_int` 定义之后新增：

```python
def _query_optional_int(query: dict[str, list[str]], key: str) -> int | None:
    value = _query_value(query, key)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise _QueryParamError(key) from exc
    if parsed < 0:
        raise _QueryParamError(key)
    return parsed
```

- [ ] **Step 4: 实现 — import `get_document_processing_max_failure_count`**

在 `web.py` 顶部从 `newspaper_translator.document_processing`（或现有 `list_document_processing_runs` 所在的 import 组）追加导入 `get_document_processing_max_failure_count`。

- [ ] **Step 5: 实现 — 改 `/api/document-processing` 路由**

把该路由整段替换为（加 try/except 与 max_failure_count）：

```python
        if path in {"/document-processing", "/api/document-processing"}:
            try:
                runs = list_document_processing_runs(
                    database_url=database_url,
                    limit=_query_int(query, "limit", default=50),
                    status=_query_value(query, "status"),
                    min_failure_count=_query_optional_int(query, "min_failure_count"),
                )
            except _QueryParamError:
                return _json_response(
                    start_response,
                    "400 Bad Request",
                    {"status": "invalid_query_parameter"},
                )
            payload = {
                "runs": _to_jsonable(runs),
                "max_failure_count": get_document_processing_max_failure_count(
                    database_url=database_url,
                ),
            }
            return _json_response(start_response, "200 OK", payload)
```

- [ ] **Step 6: 实现 — `/api/article-processing` 与 filter-options 透传**

在 `/api/article-processing` 路由的 `list_article_processing_card_views(...)` 调用里，`error_message=_query_value(query, "error_message"),` 之后加一行：

```python
                    min_failure_count=_query_optional_int(query, "min_failure_count"),
```

在 `/api/article-processing/filter-options` 路由的 `get_article_processing_filter_options_view(...)` 调用里，`step=_query_value(query, "step"),` 之后加一行：

```python
                    min_failure_count=_query_optional_int(query, "min_failure_count"),
```

> 注：filter-options 路由当前未包裹 `_QueryParamError`。`_query_optional_int` 在非法时会抛 `_QueryParamError`；为避免 500，给该路由也加与 article-processing 路由一致的 try/except → 400（若现有结构是裸调用，则包一层 try）。article-processing 路由本身已有 `except _QueryParamError` 包裹，沿用即可。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_web.py -k "max_failure_count or invalid_min_failure" -v`
Expected: PASS

- [ ] **Step 8: 回归 + 提交**

Run: `pytest tests/test_web.py -q`
Expected: PASS（全部）

```bash
git add src/newspaper_translator/web.py tests/test_web.py
git commit -m "feat: wire min_failure_count and max_failure_count through web routes"
```

---

## Task 4: 前端 — 文章处理页移除文档状态筛选行

**Files:**
- Modify: `frontend/index.html`（承载 `#document-status-filter` 的 `<div class="filter-form">` 约 103）
- Modify: `frontend/app.js`（常量区约 44；`showDocumentProcessingPage` 约 157-170；`showArticleProcessingPage` 约 173-184）
- Test: `tests/test_frontend_static.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_frontend_static.py` 的 index/app 断言测试里追加（可放入现有 `test_frontend_index_defines_dashboard_sections` 或新增方法）：

```python
    def test_article_processing_tab_can_hide_document_status_row(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()
        self.assertIn('id="document-processing-filter-form"', index_text)
        self.assertIn("documentProcessingFilterForm", app_text)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_frontend_static.py -k "document_status_row" -v`
Expected: FAIL（找不到 id / 常量名）

- [ ] **Step 3: 实现 — 给 div 加 id**

`frontend/index.html`：把承载文档状态下拉与刷新按钮的

```html
            <div class="filter-form">
              <label>
                <span>文档状态</span>
```

改为

```html
            <div id="document-processing-filter-form" class="filter-form">
              <label>
                <span>文档状态</span>
```

- [ ] **Step 4: 实现 — app.js 显隐切换**

在常量区（`documentStatusFilter` 附近，约 44 行）新增：

```js
const documentProcessingFilterForm = document.querySelector("#document-processing-filter-form");
```

在 `showDocumentProcessingPage()` 内（与 `documentRefreshButton.classList.remove("hidden");` 相邻）加：

```js
  documentProcessingFilterForm.classList.remove("hidden");
```

在 `showArticleProcessingPage()` 内（与 `documentRefreshButton.classList.add("hidden");` 相邻）加：

```js
  documentProcessingFilterForm.classList.add("hidden");
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_frontend_static.py -k "document_status_row" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/index.html frontend/app.js tests/test_frontend_static.py
git commit -m "feat: hide document status filter on article processing tab"
```

---

## Task 5: 前端 — 失败次数动态下拉

**Files:**
- Modify: `frontend/index.html`（文档筛选 div 与文章处理筛选 form 内各加一个下拉）
- Modify: `frontend/app.js`（常量；`renderFailureCountOptions`；`loadDocumentProcessing`；`loadArticleProcessingFilterOptions`；`buildDocumentProcessingQueryString`；`buildArticleProcessingQueryString`）
- Test: `tests/test_frontend_static.py`

- [ ] **Step 1: 写失败测试**

```python
    def test_failure_count_filters_present_for_documents_and_articles(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()
        self.assertIn('id="document-failure-count-filter"', index_text)
        self.assertIn('id="article-processing-failure-count-filter"', index_text)
        self.assertIn("renderFailureCountOptions", app_text)
        self.assertIn("min_failure_count", app_text)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_frontend_static.py -k "failure_count_filters" -v`
Expected: FAIL

- [ ] **Step 3: 实现 — HTML 两个空壳下拉**

文档筛选：在 `#document-processing-filter-form` 内、`<div class="filter-actions">`（刷新按钮）**之前**插入：

```html
              <label>
                <span>失败次数</span>
                <select id="document-failure-count-filter" name="document_failure_count">
                  <option value="">全部</option>
                </select>
              </label>
```

文章处理筛选：在 `#article-processing-filter-form` 内、错误原因 `<label>` **之后**、`<div class="filter-actions">` 之前插入：

```html
              <label>
                <span>失败次数</span>
                <select id="article-processing-failure-count-filter" name="article_processing_failure_count">
                  <option value="">全部</option>
                </select>
              </label>
```

- [ ] **Step 4: 实现 — app.js 常量 + 选项重建函数**

常量区新增：

```js
const documentFailureCountFilter = document.querySelector("#document-failure-count-filter");
const articleProcessingFailureCountFilter = document.querySelector("#article-processing-failure-count-filter");
```

新增重建函数（放在 `renderSelectOptions` 附近）：

```js
function renderFailureCountOptions(selectElement, maxFailureCount) {
  const previousValue = selectElement.value;
  selectElement.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "全部";
  selectElement.appendChild(allOption);
  const max = Number.isFinite(maxFailureCount) ? maxFailureCount : 0;
  for (let threshold = 1; threshold <= max; threshold += 1) {
    const option = document.createElement("option");
    option.value = String(threshold);
    option.textContent = `≥${threshold} 次`;
    selectElement.appendChild(option);
  }
  if (previousValue && Number(previousValue) <= max) {
    selectElement.value = previousValue;
  } else {
    selectElement.value = "";
  }
}
```

- [ ] **Step 5: 实现 — 文档列表加载时重建下拉 + 带参**

在 `loadDocumentProcessing()` 里 `renderDocumentList(payload.runs);` 之后加：

```js
  renderFailureCountOptions(documentFailureCountFilter, payload.max_failure_count ?? 0);
```

在 `buildDocumentProcessingQueryString()` 里，`status` 之后加：

```js
  if (documentFailureCountFilter.value) {
    params.set("min_failure_count", documentFailureCountFilter.value);
  }
```

- [ ] **Step 6: 实现 — 文章 filter-options 重建下拉 + 带参**

在 `loadArticleProcessingFilterOptions()` 里 `renderDependentErrorOptions(payload.error_messages);` 之后加：

```js
  renderFailureCountOptions(articleProcessingFailureCountFilter, payload.max_failure_count ?? 0);
```

在 `buildArticleProcessingQueryString()` 里，`step` 之后、`page` 之前加：

```js
  if (articleProcessingFailureCountFilter.value) params.set("min_failure_count", articleProcessingFailureCountFilter.value);
```

> 文章重置按钮已调用 `articleProcessingFilterForm.reset()`，会把该下拉选回首项「全部」（选项列表保留），无需额外处理。

- [ ] **Step 7: 运行测试确认通过**

Run: `pytest tests/test_frontend_static.py -k "failure_count_filters" -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add frontend/index.html frontend/app.js tests/test_frontend_static.py
git commit -m "feat: add dynamic min-failure-count filter to workbench tabs"
```

---

## Task 6: 前端 — 阅读渲染重构为工厂，详情内联文章选项卡

**Files:**
- Modify: `frontend/app.js`（`renderDetailMode`/`renderDetailImages`/`showArticleDetail` 约 641-712 重构为工厂；`showArticleProcessingDetail` 约 508；`articleProcessingOpenArticleButton` 处理器约 1102；常量区）
- Modify: `frontend/index.html`（`#article-processing-detail-view` 约 287-326 加选项卡 + 内嵌 reader DOM）
- Modify: `frontend/styles.css`（选项卡/内嵌 reader 样式）
- Test: `tests/test_frontend_static.py`

- [ ] **Step 1: 写失败测试**

```python
    def test_article_processing_detail_has_inline_article_reader(self) -> None:
        index_text = (PROJECT_ROOT / "frontend" / "index.html").read_text()
        app_text = (PROJECT_ROOT / "frontend" / "app.js").read_text()
        self.assertIn('id="ap-detail-tab-processing"', index_text)
        self.assertIn('id="ap-detail-tab-article"', index_text)
        self.assertIn('id="ap-reader-single-body"', index_text)
        self.assertIn('id="ap-reader-compare-pane"', index_text)
        self.assertIn("createArticleReader", app_text)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_frontend_static.py -k "inline_article_reader" -v`
Expected: FAIL

- [ ] **Step 3: 实现 — index.html 选项卡 + 内嵌 reader DOM**

把 `#article-processing-detail-view` 内 `<div class="detail-layout">…</div>` 整块替换为：选项卡条 + 处理信息面板（原 detail-layout 内容）+ 内嵌 reader 面板。

```html
            <div class="ap-detail-tabs">
              <button id="ap-detail-tab-processing" class="language-button active" type="button">处理信息</button>
              <button id="ap-detail-tab-article" class="language-button" type="button">文章内容</button>
            </div>

            <div id="ap-detail-processing-panel" class="detail-layout">
              <aside class="detail-sidebar">
                <div class="detail-block">
                  <h3>状态摘要</h3>
                  <p id="article-processing-detail-meta">等待加载状态...</p>
                </div>
                <div class="detail-block">
                  <h3>状态标签</h3>
                  <div id="article-processing-detail-badges" class="badge-row"></div>
                </div>
                <div class="detail-block">
                  <h3>错误摘要</h3>
                  <p id="article-processing-detail-error-summary">等待加载错误摘要...</p>
                </div>
              </aside>
              <div class="detail-main">
                <div class="detail-block">
                  <h3>文章身份</h3>
                  <div id="article-processing-identity-fields" class="key-value-list"></div>
                </div>
                <div class="detail-block">
                  <h3>运行字段</h3>
                  <div id="article-processing-detail-fields" class="key-value-list"></div>
                </div>
              </div>
            </div>

            <div id="ap-detail-article-panel" class="detail-main hidden">
              <div id="ap-reader-image-gallery" class="detail-image-gallery hidden"></div>
              <div class="detail-language-bar">
                <button id="ap-reader-mode-zh" class="language-button active" type="button">中文</button>
                <button id="ap-reader-mode-en" class="language-button" type="button">English</button>
                <button id="ap-reader-mode-compare" class="language-button" type="button">对照</button>
              </div>
              <div id="ap-reader-single-pane" class="detail-pane">
                <article>
                  <h3 id="ap-reader-single-title">等待加载标题...</h3>
                  <p id="ap-reader-single-body">等待加载正文...</p>
                </article>
              </div>
              <div id="ap-reader-compare-pane" class="detail-compare hidden">
                <article class="detail-pane">
                  <h3>中文</h3>
                  <p id="ap-reader-zh-body">等待加载中文正文...</p>
                </article>
                <article class="detail-pane">
                  <h3>English</h3>
                  <p id="ap-reader-en-body">Waiting for English body...</p>
                </article>
              </div>
            </div>
```

- [ ] **Step 4: 实现 — app.js 阅读渲染工厂**

把现有 `renderDetailMode`、`renderDetailImages`、`showArticleDetail` 三个函数替换为工厂 + 薄包装。新增工厂 `createArticleReader(elements)`：

```js
function createArticleReader(elements) {
  let readerDetail = null;

  function renderMode(mode) {
    [elements.modeZh, elements.modeEn, elements.modeCompare].forEach((button) => {
      button.classList.remove("active");
    });
    if (mode === "compare") {
      elements.modeCompare.classList.add("active");
      elements.singlePane.classList.add("hidden");
      elements.comparePane.classList.remove("hidden");
      return;
    }
    elements.singlePane.classList.remove("hidden");
    elements.comparePane.classList.add("hidden");
    if (mode === "en") {
      elements.modeEn.classList.add("active");
      elements.singleTitle.textContent = readerDetail.title_en;
      elements.singleBody.textContent = readerDetail.body_text_en;
      return;
    }
    elements.modeZh.classList.add("active");
    elements.singleTitle.textContent = readerDetail.title_zh || readerDetail.title_en;
    elements.singleBody.textContent = readerDetail.body_text_zh || readerDetail.body_text_en;
  }

  function renderImages(images) {
    elements.imageGallery.replaceChildren();
    if (!images?.length) {
      elements.imageGallery.classList.add("hidden");
      return;
    }
    images.forEach((imagePath, index) => {
      const image = document.createElement("img");
      image.className = "detail-image";
      image.src = `/api/local-image?path=${encodeURIComponent(imagePath)}`;
      image.alt = `${readerDetail?.title_zh || readerDetail?.title_en || "article"} image ${index + 1}`;
      image.loading = "lazy";
      elements.imageGallery.appendChild(image);
    });
    elements.imageGallery.classList.remove("hidden");
  }

  function render(detail) {
    readerDetail = detail;
    if (elements.title) elements.title.textContent = detail.title_zh || detail.title_en;
    if (elements.summary) elements.summary.textContent = detail.summary_zh || "当前没有中文摘要。";
    if (elements.meta) elements.meta.textContent = `${detail.source_name} · ${detail.publication_date}`;
    if (elements.tags) {
      elements.tags.replaceChildren();
      (detail.tags || []).forEach((tagText) => {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = tagText;
        elements.tags.appendChild(tag);
      });
    }
    if (elements.processing) {
      elements.processing.replaceChildren();
      Object.entries(detail.processing || {}).forEach(([key, value]) => {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = `${key}: ${value}`;
        elements.processing.appendChild(badge);
      });
    }
    renderImages(detail.images || []);
    elements.zhBody.textContent = detail.body_text_zh || "当前没有中文正文。";
    elements.enBody.textContent = detail.body_text_en;
    renderMode("zh");
  }

  elements.modeZh.addEventListener("click", () => renderMode("zh"));
  elements.modeEn.addEventListener("click", () => renderMode("en"));
  elements.modeCompare.addEventListener("click", () => renderMode("compare"));

  return {
    render,
    setMode: renderMode,
    get detail() {
      return readerDetail;
    },
  };
}
```

- [ ] **Step 5: 实现 — 独立阅读页改用工厂实例**

在工厂定义之后，用现有阅读页元素构造标准实例（这些 `detail*` 常量已在文件常量区存在）：

```js
const articleDetailReader = createArticleReader({
  title: detailTitle,
  summary: detailSummary,
  meta: detailMeta,
  tags: detailTags,
  processing: detailProcessing,
  imageGallery: detailImageGallery,
  modeZh: modeZhButton,
  modeEn: modeEnButton,
  modeCompare: modeCompareButton,
  singlePane: detailSinglePane,
  singleTitle: detailSingleTitle,
  singleBody: detailSingleBody,
  comparePane: detailComparePane,
  zhBody: detailZhBody,
  enBody: detailEnBody,
});
```

把 `showArticleDetail` 改成薄包装（保留页面级副作用与模块 `currentDetail`，供 `openSourceDocumentFromArticleDetail` 使用）：

```js
function showArticleDetail(detail) {
  currentDetail = detail;
  showDashboardSections();
  articleDetailView.classList.remove("hidden");
  articleDetailReader.render(detail);
  articleDetailView.scrollIntoView({ behavior: "smooth", block: "start" });
}
```

> 删除旧的独立 `renderDetailMode` / `renderDetailImages` 函数定义（逻辑已并入工厂）。同时删除文件底部对 `modeZhButton/modeEnButton/modeCompareButton` 的旧 `addEventListener("click", …)`（约 1139-1155），因为工厂已为这些按钮绑定事件——避免重复绑定。确认这三个旧监听器仅调用 `renderDetailMode`，删除安全。

- [ ] **Step 6: 实现 — 内嵌 reader 实例 + 选项卡常量**

常量区新增内嵌 reader 元素与选项卡按钮，并构造内嵌实例：

```js
const apDetailTabProcessing = document.querySelector("#ap-detail-tab-processing");
const apDetailTabArticle = document.querySelector("#ap-detail-tab-article");
const apDetailProcessingPanel = document.querySelector("#ap-detail-processing-panel");
const apDetailArticlePanel = document.querySelector("#ap-detail-article-panel");

const articleProcessingReader = createArticleReader({
  imageGallery: document.querySelector("#ap-reader-image-gallery"),
  modeZh: document.querySelector("#ap-reader-mode-zh"),
  modeEn: document.querySelector("#ap-reader-mode-en"),
  modeCompare: document.querySelector("#ap-reader-mode-compare"),
  singlePane: document.querySelector("#ap-reader-single-pane"),
  singleTitle: document.querySelector("#ap-reader-single-title"),
  singleBody: document.querySelector("#ap-reader-single-body"),
  comparePane: document.querySelector("#ap-reader-compare-pane"),
  zhBody: document.querySelector("#ap-reader-zh-body"),
  enBody: document.querySelector("#ap-reader-en-body"),
});

let articleProcessingReaderLoadedId = null;
```

> 内嵌实例不传 title/summary/meta/tags/processing（这些在处理面板，不在 reader 面板），工厂里已用 `if (elements.x)` 兜底跳过。

- [ ] **Step 7: 实现 — 选项卡切换 + 懒加载**

新增切换函数与按钮事件（放在 `showArticleProcessingDetail` 附近）：

```js
function showArticleProcessingProcessingTab() {
  apDetailTabProcessing.classList.add("active");
  apDetailTabArticle.classList.remove("active");
  apDetailProcessingPanel.classList.remove("hidden");
  apDetailArticlePanel.classList.add("hidden");
}

async function showArticleProcessingArticleTab() {
  apDetailTabArticle.classList.add("active");
  apDetailTabProcessing.classList.remove("active");
  apDetailProcessingPanel.classList.add("hidden");
  apDetailArticlePanel.classList.remove("hidden");

  const articleId = currentArticleProcessingRun?.article_id;
  if (!articleId) {
    setStatus("当前文章处理记录没有可用的文章标识。");
    return;
  }
  if (articleProcessingReaderLoadedId === articleId) {
    return;
  }
  setStatus("正在加载文章内容...");
  const payload = await fetchJson(`/api/articles/${articleId}`);
  articleProcessingReader.render(payload.article);
  articleProcessingReaderLoadedId = articleId;
  setStatus("文章内容已加载。");
}

apDetailTabProcessing.addEventListener("click", () => {
  showArticleProcessingProcessingTab();
});

apDetailTabArticle.addEventListener("click", async () => {
  try {
    await showArticleProcessingArticleTab();
  } catch (error) {
    console.error(error);
    setStatus("文章内容加载失败。");
  }
});
```

在 `showArticleProcessingDetail(run)` 函数体开头（`currentArticleProcessingRun = run;` 之后）加：默认回到处理信息选项卡并清空已加载标记：

```js
  articleProcessingReaderLoadedId = null;
  showArticleProcessingProcessingTab();
```

- [ ] **Step 8: 实现 — 「查看文章」按钮改为切换选项卡**

把 `articleProcessingOpenArticleButton` 的事件处理器（约 1102）替换为：

```js
articleProcessingOpenArticleButton.addEventListener("click", async () => {
  try {
    await showArticleProcessingArticleTab();
  } catch (error) {
    console.error(error);
    setStatus("文章内容加载失败。");
  }
});
```

- [ ] **Step 9: 实现 — styles.css 选项卡间距**

在 `frontend/styles.css` 末尾追加：

```css
.ap-detail-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
```

- [ ] **Step 10: 运行静态测试确认通过**

Run: `pytest tests/test_frontend_static.py -q`
Expected: PASS（含 `inline_article_reader`）

- [ ] **Step 11: 手动验证（真实渲染）**

前端无 JS 单测，需真实跑一遍确认行为：用 `/run` 或 `verify` 技能启动 web 服务，打开工作台 →「文章处理」→ 任一记录详情：
- 默认显示「处理信息」面板；
- 点「文章内容」或「查看文章」→ 拉取并显示正文，中文/English/对照 三种模式与图片正常；
- 切回「处理信息」内容保留；
- 独立阅读页（首页文章卡片）语言切换仍正常（验证工厂重构未破坏旧路径）。

- [ ] **Step 12: 提交**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: inline article reader tab in article processing detail"
```

---

## 收尾

- [ ] **全量回归**

Run: `pytest -q`
Expected: PASS（全部）

- [ ] **完成分支**

实现完成、测试通过后，用 `superpowers:finishing-a-development-branch` 技能决定合并/PR/清理方式。

---

## Self-Review 备注（已核对）

- **Spec 覆盖**：改动 1 → Task 4；改动 2 后端 → Task 1/2/3，前端 → Task 5；改动 3 → Task 6。测试分布与 spec「测试」节一致。
- **类型一致**：后端新参数统一命名 `min_failure_count`；视图字段 `max_failure_count`；前端统一 query key `min_failure_count`、响应 key `max_failure_count`、函数 `renderFailureCountOptions` / `createArticleReader`。
- **无占位符**：所有代码步骤均给出完整代码。
- **已知弱点**：前端缺 JS 单测，Task 6 行为正确性依赖 Step 11 手动验证（已显式列出）；`test_web.py` 的请求 helper 名为占位，实现者需对齐该文件既有写法（Task 3 Step 1 已标注）。
