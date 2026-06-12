# 工作台筛选调整与文章内联阅读设计

日期：2026-06-12

## 背景

运营工作台（处理筛选面板）分为「文档处理」和「文章处理」两个标签页。当前存在三个体验问题：

1. 「文档状态」筛选行（`#document-status-filter`）只属于文档标签页，但切到文章标签页时仍残留可见——`showArticleProcessingPage()` 只隐藏了刷新按钮，没有隐藏承载该下拉的 `<div class="filter-form">`。
2. 文档与文章处理记录都存有 `automatic_failure_count`，但筛选器无法按失败次数聚焦（如「只看反复失败的」）。
3. 文章处理详情里的「查看文章」按钮直接 `window.location.hash = article/{id}` 跳转到阅读首页，离开了运营上下文；运营希望在详情内就能看到文章正文。

## 目标

- 文章处理页不再显示「文档状态」筛选行。
- 文档页与文章页都新增「失败次数 ≥ 阈值」筛选。
- 文章处理详情内通过选项卡切换查看文章正文，复用完整阅读体验（中文/English/对照 + 图片 + 标签），不跳转、不重复实现渲染逻辑。

## 非目标（YAGNI）

- 批量重试（retry-batch）按失败次数筛选——保持 `_RETRY_BATCH_FILTER_KEYS` 不变。
- 文档详情页内联文章阅读——本次只改文章处理详情。

---

## 改动 1：文章处理页移除「文档状态」筛选行

**前端（纯前端，无后端改动）**

- `frontend/index.html`：给当前承载 `#document-status-filter` 的无名 `<div class="filter-form">`（约 index.html:103）加 id `document-processing-filter-form`。
- `frontend/app.js`：
  - 新增常量 `documentProcessingFilterForm = document.querySelector("#document-processing-filter-form")`。
  - `showDocumentProcessingPage()`：`documentProcessingFilterForm.classList.remove("hidden")`。
  - `showArticleProcessingPage()`：`documentProcessingFilterForm.classList.add("hidden")`。
  - 这与现有 `articleProcessingFilterForm` 的显隐切换方式对称。

---

## 改动 2：文档/文章两页新增「失败次数 ≥ 阈值」筛选

### 语义

- 匹配逻辑：`automatic_failure_count >= N`（含 N）。
- 阈值选项**动态生成**：后端暴露当前最大失败次数 `max_failure_count = MAX(automatic_failure_count)`，前端据此生成 `全部 / ≥1 次 … ≥max 次`。`max == 0`（无任何失败）时只有「全部」。
- `max_failure_count` 取**全局值（不随当前筛选缩放）**，确保已选阈值不会因列表过滤后行数变少而消失。
- 缺省（"全部"）时不附带 `min_failure_count` 参数。

### 前端

- `frontend/index.html`：在文档筛选表单与文章处理筛选表单各加一个**空壳**下拉（选项由 JS 注入）：
  ```html
  <label>
    <span>失败次数</span>
    <select id="document-failure-count-filter" name="document_failure_count">
      <option value="">全部</option>
    </select>
  </label>
  ```
  文章侧同构，id 用 `article-processing-failure-count-filter`、name 用 `article_processing_failure_count`。
- `frontend/app.js`：
  - 新增两个常量绑定上述元素。
  - 新增 `renderFailureCountOptions(selectEl, maxFailureCount)`：清空后重建 `全部` + `≥1 次 … ≥max 次`；重建前记下当前 `value`，若仍 `<= max` 则保留选中，否则回落「全部」。
  - **文档**：`max_failure_count` 来自 `/api/document-processing` 列表响应（见后端），每次刷新列表后调用 `renderFailureCountOptions`。
  - **文章**：`max_failure_count` 来自 `/api/article-processing/filter-options`，在既有 `loadArticleProcessingFilterOptions`（填充 source/step/error 的同一处）里一并重建。
  - `buildDocumentProcessingQueryString()` / `buildArticleProcessingQueryString()`：若有值，`params.set("min_failure_count", value)`。
  - 文章筛选重置（`article-processing-reset-filters`）清空该控件选中值（保留选项列表）。

### 后端

- `src/newspaper_translator/document_processing.py` → `list_document_processing_runs`：
  - 新增参数 `min_failure_count: int | None = None`。
  - 把当前「status 有/无」两分支重构为动态拼接 WHERE：可叠加 `status = ?` 与 `automatic_failure_count >= ?`，再统一 `ORDER BY ... LIMIT ?`。
  - 新增 `get_document_processing_max_failure_count(*, database_url) -> int`：`SELECT COALESCE(MAX(automatic_failure_count), 0) FROM document_processing_runs`（全局，不带筛选）。
- `src/newspaper_translator/api/queries.py`：
  - `_build_article_processing_where_clauses`：新增 `min_failure_count: int | None = None`，追加 `clauses.append("r.automatic_failure_count >= ?")`、`params.append(min_failure_count)`。
  - `list_article_processing_card_views`：新增同名参数并透传给 where 构造器（两处重载签名同步更新）。
  - `get_article_processing_filter_options_view`：
    - 新增同名参数并透传，保证交叉筛选时其他下拉选项与失败次数过滤一致。
    - `ArticleProcessingFilterOptionsView` 新增字段 `max_failure_count: int`，由全局 `SELECT COALESCE(MAX(r.automatic_failure_count), 0) FROM article_processing_runs r`（**不带任何筛选**）计算。
- `src/newspaper_translator/web.py`：
  - 新增解析辅助：`_query_optional_int(query, name)`——缺省返回 `None`，非法（非整数/负数）抛 `_QueryParamError`。
  - `/api/document-processing`：解析 `min_failure_count` 传入 `list_document_processing_runs`；响应 payload 增加 `"max_failure_count": get_document_processing_max_failure_count(...)`。该路由当前未包裹 `_QueryParamError`→400，需补上 try/except 返回 `{"status": "invalid_query_parameter"}`。
  - `/api/article-processing`：解析 `min_failure_count` 透传。
  - `/api/article-processing/filter-options`：解析 `min_failure_count` 透传（响应已含 `max_failure_count` 字段）。

---

## 改动 3：文章处理详情内联阅读（选项卡切换，复用阅读渲染）

### 复用策略

当前阅读渲染（`showArticleDetail` / `renderDetailMode` / `renderDetailImages`）直接引用模块级 DOM 常量（`detailSingleTitle`、`detailComparePane`、`detailImageGallery` 等），无法在第二处复用。

重构为工厂：

```js
function createArticleReader(elements) {
  // elements: { title, summary, meta, tags, processing,
  //             imageGallery, modeZh, modeEn, modeCompare,
  //             singlePane, singleTitle, singleBody,
  //             comparePane, zhBody, enBody }
  let currentDetail = null;
  function renderMode(mode) { /* 原 renderDetailMode 逻辑，引用 elements.* */ }
  function renderImages(images) { /* 原 renderDetailImages 逻辑 */ }
  function render(detail) { /* 原 showArticleDetail 中的填充逻辑（不含 show/scroll 等页面级副作用） */ }
  // 绑定 elements.modeZh/En/Compare 的 click → renderMode
  return { render, setMode: renderMode };
}
```

- 独立阅读页：用现有 DOM 元素构造一个 reader 实例；`showArticleDetail`/`loadArticleDetail` 改为调用该实例的 `render()`，并保留页面级副作用（显示 section、滚动）。
- 处理详情内：构造第二个 reader 实例，绑定下述新增的内嵌 DOM。

> 注意：保持 `currentDetail`（独立阅读页用于「查看源文档」跳转）等既有引用语义不变；工厂内部各自维护自己的 `currentDetail`，独立阅读页继续维护其原有的模块级 `currentDetail` 供 `openSourceDocumentFromArticleDetail` 使用。

### HTML

在 `#article-processing-detail-view` 内：
- 顶部加选项卡切换：「处理信息 / 文章内容」（沿用现有 `.language-button`/nav 类样式，二选一显示）。
- 加内嵌 reader 容器（默认隐藏），DOM 结构镜像阅读页：图片廊、`中文/English/对照` 语言条、单栏面板、对照面板。所有 id 加前缀（如 `ap-reader-*`）避免与阅读页冲突。
- 现有「处理信息」内容（`detail-layout`：状态摘要/标签/错误/身份/运行字段）包进「处理信息」面板。

### app.js

- `showArticleProcessingDetail(run)`：进入时默认激活「处理信息」选项卡，重置内嵌 reader 的「已加载」标记。
- 选项卡切换处理：
  - 点「处理信息」：显示处理面板，隐藏 reader 容器。
  - 点「文章内容」：显示 reader 容器；若该 `article_id` 尚未加载，`fetchJson(/api/articles/{article_id})` → `apReader.render(payload.article)`，并缓存避免重复请求；缺 `article_id` 时 `setStatus` 提示。
- 「查看文章」按钮（`#article-processing-open-article-button`）：改为触发「文章内容」选项卡切换（不再 `window.location.hash`）。「查看所属文档」保持原跳转。

### 后端

无改动，复用 `/api/articles/{id}`。边界：`article_id` 尚未富化时该接口回退英文正文，reader 正常显示英文（中文区显示既有占位文案）。

---

## 测试

- `tests/test_document_run_store.py`：`list_document_processing_runs` 按 `min_failure_count` 过滤（含与 status 叠加、阈值边界 = N 命中、< N 排除）；`get_document_processing_max_failure_count` 返回全局最大值、空表返回 0。
- `tests/test_api_queries.py`：`list_article_processing_card_views` 的 `min_failure_count` 过滤行为；`get_article_processing_filter_options_view` 的 `min_failure_count` 透传与 `max_failure_count` 字段（全局最大、不随其他筛选缩放、空表为 0）。
- `tests/test_web.py`：`/api/document-processing` 响应含 `max_failure_count` 且透传 `min_failure_count`；`/api/article-processing` 透传 `min_failure_count`；`/api/article-processing/filter-options` 响应含 `max_failure_count`；非法 `min_failure_count` 返回 400。
- `tests/test_frontend_static.py`：断言新增的失败次数下拉（空壳）、内嵌 reader 容器、文章/处理信息选项卡元素存在；断言文档状态行具备可切换 id。

## 影响面

- 后端改动集中在 `document_processing.py`、`api/queries.py`、`web.py`，均为新增可选参数，向后兼容。
- 前端改动集中在 `index.html`、`app.js`、`styles.css`（选项卡/内嵌 reader 样式）。
- 数据库无 schema 变更。
