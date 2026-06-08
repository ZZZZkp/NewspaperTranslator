# MinerU 限流稳健化设计

- 日期：2026-06-08
- 分支：`feature/deepseek-and-page-sliced-mineru`
- 状态：已通过头脑风暴评审，待实现计划

## 背景与动机

文档解析阶段通过 MinerU 把 PDF 拆成单页文件后分批上传、轮询、下载结果。当前实现对
MinerU 的账号级限流非常脆弱，2026-06-08 的生产冒烟测试暴露了这一点：一篇 `max_results:1`
的单篇文档在第一个 MinerU 请求上即刻收到 `HTTP Error 429: Too Many Requests`，步内 3 次
固定 1 秒重试全部 429，`automatic_failure_count` 涨到 4，文档被判 `failed_terminal`，
只能人工捞回。

### MinerU 的真实限制（账号级，所有并发共享）

- **提交任务：50 文件/分钟** ← 真正的瓶颈
- 获取结果：1000 次/分钟 ← 远超实际需要，基本不构成约束

瓶颈是一个**速率**（50 文件/分钟），不是并发数。关键事实：`parse_pdf_by_pages` 每个 batch
的 `file-urls/batch` POST 会一次性声明最多 30 个文件（`max_batch_size=30`）。因此一篇 60 页的
报纸 = 30+30 两批，若落在同一分钟内提交就是 60 文件 > 50 → 429。**即使只有一篇文档、并发为 1，
也可能撞 429。** 单纯限制并发数无法守住这条速率线。

### 当前实现的三个缺口

1. **并发配额是文档独立的**：`run_document_processing_drain` 用 `ThreadPoolExecutor`
   （`DOCUMENT_WORKER_CONCURRENCY=2`）并发处理多篇文档，每篇各自向 MinerU 提交，彼此之间
   没有任何账号级的全局节流。
2. **重试粒度是整体的**：`parse_pdf_by_pages` 按 30 页分批上传，任一页/批失败即整个
   `parse_persist` 步抛错，`_run_step_with_retry` 从第 1 页重跑，重新上传所有批次——重传正是
   烧掉提交配额、触发 429 的根源。
3. **退避对 429 无效**：`_request_with_retries` 只对 `URLError` 做固定 1 秒退避、最多 3 次；
   `urlopen` 对 429 抛 `HTTPError`，3 次快速重试后原样抛出。既不读 `Retry-After`，也没有分钟级
   退避，且 429 被当作"真实失败"烧掉终态预算。

## 设计目标

让解析阶段在 MinerU 账号级限流下保持稳健：

1. 从源头把提交速率压在 50 文件/分钟线下，让 429 几乎不发生。
2. 万一仍触发 429，全局暂停所有提交、分钟级退避后恢复，而不是快速重试硬撞。
3. 失败重试做到页级断点续传：**已提交/已完成的页绝不重新上传**，避免重传烧配额。
4. 纯限流导致的失败不应把文档判为永久失败。

## 架构总览

新增一个账号级**提交节流器** `MineruSubmissionThrottle`，作为 `MineruClient` 的成员，承担
令牌桶控速与 429 全局熔断；改造传输层让 429 / `Retry-After` 可见；新增一张页级状态表支撑断点
续传；并为"限流失败"开一条不计入终态预算的状态路径。

```
process_document
  └─ parse_persist 步
       └─ persist_document_articles
            └─ MineruClient.parse_pdf_by_pages
                 ├─ 读 mineru_page_parse_state：done 跳过 / submitted 重新轮询 / pending 走提交
                 ├─ 提交前：throttle.acquire(N)   ← 令牌桶 + 暂停门
                 ├─ 上传 / 轮询 / 下载 / 存盘
                 └─ 每页存盘后写 state=done
       └─ 失败为 MineruRateLimitError → failed_retryable（不计终态）
          其它失败 → 现有 automatic_failure_count / failed_terminal 语义
```

## 组件 1：`MineruSubmissionThrottle`（账号级提交节流器）

进程内唯一实例。当前每个 worker 进程只构造一个 `MineruClient` 并被 `DOCUMENT_WORKER_CONCURRENCY`
个线程共享，因此节流器**作为该 `MineruClient` 的成员字段**即可天然全局共享，无需独立的模块级单例。
内部状态用锁保护，可被多线程安全调用。

### 令牌桶（控速率）

- 补充速率 = `MINERU_SUBMIT_RATE_PER_MIN`（默认 **45**，在 50 线下留余量）。
- 容量 = 同速率值（允许一次性攒满一分钟的额度）。
- 提交一个含 N 个文件的 batch 前调用 `acquire(N)`：令牌不足则阻塞等待补满。
- 计数口径 = `file-urls/batch` POST 中声明的文件数（"提交任务"的真实单位）。
  - **待核实假设**：50/分钟按 batch POST 声明的文件数计，而非 PUT 上传次数。实现以"提交文件数"
    为令牌单位；若后续确认口径不同，仅需调整 `acquire` 的调用点，不影响整体结构。
- 使用可注入的 `monotonic` 时钟，单测以假时钟驱动，不睡真时间。

### 全局暂停门（429 熔断）

- 任一线程收到 429 → 设进程级 `paused_until = now + max(Retry-After, MINERU_RATE_LIMIT_PAUSE_SECONDS)`
  （`MINERU_RATE_LIMIT_PAUSE_SECONDS` 默认 **120**）。
- 所有线程在 `acquire()` 入口先阻塞到 `paused_until`，再尝试取令牌。
- 一次解析操作内，若穿过 `MINERU_RATE_LIMIT_MAX_PAUSES`（默认 **2**）个暂停周期后其请求仍是
  429，则抛 `MineruRateLimitError`，由上层转为 `failed_retryable`。
- `Retry-After` 解析支持秒数格式；无法解析或缺失时回退到默认暂停时长。

### 暂停时长与锁超时的关系

最多 2 个暂停周期 ≈ 4 分钟，安全地小于 `DOCUMENT_LOCK_TIMEOUT_SECONDS`（600s）与
`RUNNING_TIMEOUT_SECONDS`（14400s），不会被并发抢占或 stale 回收误判，因此**无需改动锁相关配置**。

## 组件 2：传输层改造（让 429 / `Retry-After` 可见）

当前 `_UrllibTransport` 用 `request.urlopen`，对 429 抛 `HTTPError`（`URLError` 的子类）；
`_request_with_retries` 捕获 `URLError` 做 3 次固定 1 秒重试后原样抛出，`Retry-After` 不可见。

改造：

- `_TransportResponse` 增加 `headers: dict[str, str]` 字段。
- `_UrllibTransport.request` 捕获 `HTTPError`，把 4xx/5xx 同样封装为带 `status_code` / `body` /
  `headers` 的 `_TransportResponse` 返回（而非抛异常）。真正的网络层错误（非 HTTP 的 `URLError`）
  仍按原样抛出。
- `_request_with_retries` 保留对非 HTTP `URLError` 的 1 秒重试；HTTP 状态码（含 429）作为正常
  返回值上交给调用方/节流器判断。429 不再走固定 1 秒重试，改由暂停门处理。

## 组件 3：页级断点续传状态表

### 新表 `mineru_page_parse_state`

主键 `(document_key, page_number)`：

| 列 | 说明 |
| --- | --- |
| `document_key` | 文档键 |
| `page_number` | 物理页号 |
| `batch_id` | 该页所属 MinerU 批次 id |
| `file_name` | 上传文件名 |
| `state` | `pending` / `submitted` / `done` |
| `full_zip_url` | 结果 zip 地址（已知时） |
| `markdown_path` | 已抽取 markdown 路径（`done` 时） |
| `created_at` / `updated_at` | 时间戳 |

通过 Alembic 迁移新增（与现有迁移串行化机制一致）。

### `parse_pdf_by_pages` 改造

按页续传：

1. 拆分单页文件后，读取该 `document_key` 已有的页状态。
2. 对每一页分类处理：
   - `done`：跳过，直接复用 `markdown_path` 的内容参与合并。
   - `submitted`（已上传但结果未存盘）：**直接重新轮询其 `batch_id`**（1000/分钟那条线很宽），
     下载、抽取、存盘、置 `done`——**不重新上传，不消耗提交令牌**。
   - `pending` 或表中不存在：组成新 batch，`throttle.acquire(N)` → 上传 → 记 `submitted` →
     轮询 → 下载 → 存盘 → 置 `done`。
3. 每页结果存盘后立即写 `state=done`（含 `markdown_path`）。
4. 全部页 `done` 后照旧合并为 `full-pages.md` 并返回 `MineruParsedDocument`。

键设计采用 `(document_key, page_number)`，不引入 PDF 内容哈希做失效——`document_key` 本身已是
内容派生，同键即同内容。状态在文档成功后保留（幂等：再次解析会全部命中 `done`，从存盘 markdown
直接重建相同输出）。

## 组件 4：失败状态语义

- 抛出 `MineruRateLimitError`（纯限流耗尽）→ 文档转 `failed_retryable`，**不** `++`
  `automatic_failure_count`；锁照常释放；下一轮 processing tick 续传重试。
- 其它真实错误 → 维持现有 `automatic_failure_count` / `failed_terminal` 语义不变。
- 实现路径：`process_document` 的 parse 步识别 `MineruRateLimitError`，走一条不计入终态预算的
  `failed_retryable` 直达分支（`fail_document_processing_run` 增加"限流失败不计数"的入参或单独
  函数）。`_run_step_with_retry` 对限流错误不做步内重试（直接上交，由节流器的暂停门负责等待）。

## 新增配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MINERU_SUBMIT_RATE_PER_MIN` | `45` | 令牌桶补充速率（文件/分钟），压在 50 线下留余量 |
| `MINERU_RATE_LIMIT_PAUSE_SECONDS` | `120` | 429 后全局暂停的默认时长 |
| `MINERU_RATE_LIMIT_MAX_PAUSES` | `2` | 单次解析内最多穿过的暂停周期数，超过即抛 `MineruRateLimitError` |

`max_batch_size` 维持 30（暂不做成配置，YAGNI）。`DOCUMENT_LOCK_TIMEOUT_SECONDS` 等锁配置不变。

## 测试策略（TDD）

- **节流器单测**（假 `monotonic` + 假 `sleep`，不睡真时间）：
  - 令牌桶限速：连续 `acquire` 超过速率时按预期阻塞、补满后放行。
  - `acquire(N)` 对 N 文件批次的阻塞/补满行为。
  - 收到 429 设置 `paused_until`，并按 `max(Retry-After, default)` 取值。
  - 穿过超额暂停周期后抛 `MineruRateLimitError`。
- **传输层单测**：注入假 transport，断言 429/5xx 被封装为带 `headers` 的 `_TransportResponse`，
  `Retry-After` 可被读到；非 HTTP `URLError` 仍按网络错误重试。
- **断点续传单测**：假 transport 模拟"第一批成功、第二批 429"，断言重试时第一批的页**不重新上传**
  （无新 `file-urls/batch` 提交），`submitted` 页只重新轮询，最终合并输出正确。
- **状态语义单测**：限流失败 → 文档 `failed_retryable` 且 `automatic_failure_count` 不变；
  其它失败 → 现有终态语义不变。
- 复用现有 `test_mineru.py` / `test_process_document.py` / `test_article_pipeline.py` 的夹具与
  假对象风格。

## 范围与非目标

- **范围内**：解析阶段（`parse_persist`）的 MinerU 提交节流、429 熔断、页级断点续传、限流失败状态
  语义、相关配置与迁移。
- **非目标**：跨进程 / 多 worker 副本的分布式限流（当前单 worker 副本，节流器内部接口预留为日后
  可替换为 DB 锁）；DeepSeek 文章富化阶段的限流；`max_batch_size` 的动态调优；MinerU 计数口径的
  在线自适应。
```
