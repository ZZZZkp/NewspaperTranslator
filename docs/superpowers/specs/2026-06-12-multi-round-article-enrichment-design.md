# 多轮对话文章 Enrich 改造设计

- 日期：2026-06-12
- 状态：已确认，待实现计划
- 涉及 provider：DeepSeek（生产路径）+ Gemini（代码内备用路径）

## 1. 背景与目标

当前 `enrich_article` 在两次独立的单轮 LLM 调用中完成全部富化：

- `translator(article)` —— 在一次调用里同时做**广告判断 + 翻译**，返回 `ArticleTranslationResult`。
- `summarizer_tagger(...)` —— 在一次调用里同时做**摘要 + 标签**，返回 `ArticleSummaryTagResult`。

`llm.py` 的 `ChatJsonClient` 只支持单轮（只发一条 user 消息），两次调用之间没有任何上下文共享。

本次改造目标：

1. 改为**一次多轮对话**，依次执行四个步骤：广告判断 → 翻译 → 摘要 → 标签提取。后续步骤复用对话上下文，不再重复发送原文。
2. **每一步**失败（格式错误或网络失败）都有 **2 次**从上一个成功步骤开始的重试机会（每步最多 3 次尝试）。
3. 文章阶段从原来的 `enrich` / `completed` 二态，改为按步骤推进的多阶段，并为广告增加独立终态。

参考：DeepSeek 多轮对话示例 <https://api-docs.deepseek.com/zh-cn/guides/multi_round_chat>（把每一轮的 user/assistant 消息累积进 `messages` 数组一起发送）。

## 2. 范围

### 2.1 改动

- `llm.py`：新增多轮发送能力。
- 新增 `enrichment_conversation.py`：四步定义 + 多轮驱动器 + 重试逻辑。
- `deepseek.py` / `gemini.py`：移除旧的 translator/summarizer 类，改为提供多轮发送适配器与 enricher 工厂；现有的连续性匹配类（`*ContinuationMatcher`）不动。
- `article_enrichment.py`：`enrich_article` 接口从 `translator` + `summarizer_tagger` 改为单个 `enricher`，并新增可选 `on_step_advance` 回调。
- `document_processing.py`：文章阶段（`current_step`）状态机改造与实时推进。
- `worker.py` / `manage.py`：装配单个 enricher，并透传新的 step 重试上限配置。
- `frontend/app.js`：阶段 key → 中文标签映射。
- 测试：富化测试改写、驱动器单测、provider 适配器单测、阶段流转断言。

### 2.2 不改动

- `article_enrichment_runs` / `article_enrichment_outputs` 表结构与 `record_article_enrichment_outputs` 的三状态字段（`translation_status` / `summary_status` / `tagging_status`）保持不变。
- `current_step` 为自由文本列，新增取值**无需迁移**。
- 阅读层（`api/queries.py`）对 `skipped_advertisement` / `partial` 的既有处理不变。

## 3. 多轮对话与四步流程

### 3.1 对话传输（`llm.py`）

`ChatJsonClient` 新增多轮发送：输入 `messages: list[{"role": "user"|"assistant", "content": str}]`，POST 完整数组，返回 assistant 文本（沿用既有的 `complete_json_text` 解析与状态码校验）。`temperature=0`、`response_format={"type":"json_object"}` 不变。

- DeepSeek、Gemini-openai-compat 模式：直接使用 OpenAI `messages` 形态。
- Gemini-native 模式：把 `role:user → user`、`role:assistant → model` 映射进 `contents` 数组，由 `gemini.py` 的 payload 构造器负责。

### 3.2 四步定义（`enrichment_conversation.py`）

每一步 = `build_user_message(ctx)` + `parse(text) -> data`（校验逻辑从现有 `deepseek.py` / `gemini.py` 抽取并去重）。

1. **广告判断**：发送完整文章（title + body）。返回 `{"content_type":"article|advertisement|uncertain","classification_reason":"..."}`。
2. **翻译**：依赖上下文（原文已在历史中），仅追加简短指令。返回 `{"translated_title_zh":"...","translated_body_zh":"..."}`；`article`/`uncertain` 时两者非空。
3. **摘要**：返回 `{"summary_zh":"..."}`，单段落。
4. **标签**：返回 `{"tags":[...]}`，3–8 个，去重、去前导 `#`。

校验失败（缺字段、枚举非法、标签数量越界、JSON 解析失败等）统一抛 `LlmProviderError` 子类，被驱动器视为该步失败。

### 3.3 驱动器

`MultiRoundArticleEnricher(send, *, step_retry_limit=2, on_step_advance=None)`：

- `send(messages) -> str`：provider 注入的传输适配器，把传输/网络错误转成 `LlmProviderError`。
- 维护 `committed_messages` = 上一个成功步骤之后的对话状态。
- 对每一步：
  1. 调用 `on_step_advance(stage_key)`（进入该步时，stage 为“正在/等待该步”）。
  2. 从 `committed_messages` 复制一份，追加本步 user 消息。
  3. `send` + `parse`。成功 → 把 assistant 文本作为一轮追加进 `committed_messages`，记录结果，进入下一步；失败 → 从同一 `committed_messages` 重试，最多 `step_retry_limit` 次（共 3 次尝试）。
  4. 重试用尽仍失败 → 停止后续步骤，返回带 `failed_step` 的结果。
- 第 1 步返回 `advertisement` → 立即停止（不进入翻译/摘要/标签）。
- 重试为**同请求重发**（temperature 固定 0）：可恢复网络抖动；确定性的格式错误会在用尽后落到 partial/failed，而非空转。**不**做温度抬升或纠错追加消息。

返回 `EnrichmentResult`：

```
content_type: "article" | "advertisement" | "uncertain" | None   # None 表示广告判断步失败
classification_reason: str | None
translation_status / summary_status / tagging_status: "succeeded" | "failed" | "skipped"
translated_title_zh / translated_body_zh: str | None
summary_zh: str | None
tags: list[str]
failed_step: str | None      # "ad_judgment" | "translation" | "summary" | "tagging"
error_message: str | None
```

### 3.4 Provider 适配器

- `DeepSeekArticleEnricher` / `GeminiArticleEnricher` 工厂：用各自的传输 + 线格式构造 `send` 适配器，返回装好的 `MultiRoundArticleEnricher`。
- 旧类 `DeepSeekArticleTranslator` / `DeepSeekArticleSummarizerTagger` / `GeminiArticleTranslator` / `GeminiArticleSummarizerTagger` 删除，其 prompt 与校验逻辑迁入共享四步定义。

## 4. `enrich_article` 落库映射

接口：`enrich_article(..., enricher, on_step_advance=None, force_reenrich=False)`，调用一次 `enricher(article)` 得到 `EnrichmentResult`，映射到既有富化表：

| EnrichmentResult 情况 | enrichment run 状态 | 落库内容 |
|---|---|---|
| 广告判断步失败（`failed_step="ad_judgment"`） | `failed` | 不落 outputs |
| `content_type == "advertisement"` | `skipped_advertisement` | translation/summary/tagging = `skipped`，content_type=advertisement |
| 翻译步失败 | `failed` | 不落 outputs（与现状一致） |
| 摘要步失败（翻译已成功） | `partial` | 落已成功的翻译；summary/tagging = `failed` |
| 标签步失败（摘要已成功） | `partial` | 落翻译 + 摘要；tagging = `failed` |
| 四步全成功 | `succeeded` | 全量落库 |

注：`partial` 比现状更细——现状 summary/tags 是一个整体，现在摘要成功而标签失败时可单独保留摘要（`summary_status="succeeded"`, `tagging_status="failed"`）。

`on_step_advance` 透传给驱动器，使阶段可在 enrich 调用过程中实时推进（见 §5）。`enrich_document_articles`、`manage.py` 等无 processing run 的调用方传 `None`。

## 5. 文章阶段模型（`current_step`）

### 5.1 阶段取值

| stage key | 中文标签 | 作为停留态的含义 |
|---|---|---|
| `await_ad_judgment` | 等待广告判断 | 入队 / 广告判断步失败 |
| `await_translation` | 等待翻译 | 广告判断完成，翻译失败 |
| `await_summary` | 等待摘要 | 翻译完成，摘要失败（partial） |
| `await_tagging` | 等待标签 | 摘要完成，标签失败（partial） |
| `completed` | 完成 | 四步全成功 |
| `classified_as_advertisement` | 判定为广告 | 广告判断返回 advertisement（终态） |

语义：`current_step` = 文章**正在/等待执行**的步骤。DB 存稳定英文 key，前端做中文映射。

### 5.2 实时推进

驱动器进入每一步时调用 `on_step_advance(stage_key)`。`process_article_processing_run` 注入回调，调用新增的 `advance_article_processing_step(database_url, article_key, current_step)`（仅更新 `current_step` + `updated_at`，DB-retry 包装，不动 status/锁）。运行期该 run 处于 `running` 且被本 worker 持锁，写入安全。终态由现有 succeed/fail 函数收尾覆盖。

### 5.3 写入点改动（`document_processing.py`）

- 创建（约第 339 行）：初始 `current_step` `"enrich"` → `"await_ad_judgment"`。
- 输入变更重置为 pending（约第 384 行）：`"enrich"` → `"await_ad_judgment"`。
- `succeed_article_processing_run`：新增 `current_step` 参数（默认 `"completed"`）；`process_article_processing_run` 在富化为 advertisement 时传 `"classified_as_advertisement"`，否则 `"completed"`。
- 未变更哈希的成功捷径（约第 366 行）：保留既有终态（若上次是 `classified_as_advertisement` 不强制改为 `completed`）。
- 失败路径：`process_article_processing_run` 不再硬编码 `failed_step="enrich"`，改为按 `EnrichmentResult.failed_step` 映射出阶段 key 传给 `fail_article_processing_run`（其 `current_step = failed_step`）。

### 5.4 前端

`frontend/app.js` 当前直接渲染 `current_step` 原值（`run.current_step`，今天显示 `enrich`/`completed`）。新增 stage key → 中文标签映射用于展示；处理记录筛选下拉（来自 distinct `current_step`）同步用映射展示。

## 6. 配置

新增 `ENRICHMENT_STEP_RETRY_LIMIT`（默认 2），表示**对话内每步**的重试上限，经 `worker.py` / `manage.py` 透传给 enricher。与既有的**run 级** `STEP_RETRY_LIMIT`（调度器对整篇文章的自动重试上限，默认 2）相互独立、互不影响。

## 7. 受影响调用点

- `worker.py`：`build_process_one_document_from_env`、`build_process_one_article_from_env` —— 构造单个 `DeepSeekArticleEnricher` 并透传。
- `document_processing.py`：`process_document` → `process_article_processing_run` / `enrich_document_articles` —— 参数由 `translator`+`summarizer_tagger` 改为 `enricher`；`process_article_processing_run` 额外装配 `on_step_advance`。
- `manage.py`：`phase3-enrich-article` —— 构造单个 enricher。

## 8. 测试计划

- **驱动器单测**（fake `send`）：重试用尽落 partial/failed；广告短路；摘要成功而标签失败的 partial；`on_step_advance` 触发顺序（`await_ad_judgment`→`await_translation`→`await_summary`→`await_tagging`）。
- **`tests/test_article_enrichment.py` 改写**：fakes 收敛为单个 fake `enricher`；新增各落库映射断言（含细化后的 partial）与阶段流转断言。
- **provider 适配器单测**（fake transport）：多轮 `messages`/`contents` 载荷形态；DeepSeek 与 Gemini 两种线格式。
- 回归：阅读层对 `skipped_advertisement`/`partial` 的既有查询不受影响。

## 9. 风险与权衡

- **温度 0 下的格式错误重试**：同请求重发对确定性格式错误无效，会直接用尽并落 partial/failed。鉴于 `json_object` 模式下格式错误罕见，且确定性错误多重试也无益，接受此权衡，不引入温度抬升/纠错消息。
- **跨层回调**：`on_step_advance` 让 `enrich_article` 触达文章处理层的 `current_step`。通过可选回调 + 由 `process_article_processing_run` 注入实现来保持解耦，其他调用方传 `None`。
- **Gemini 多轮**：native 模式需 user/model 角色映射，已在 payload 构造器内处理；生产路径为 DeepSeek，Gemini 风险较低。
