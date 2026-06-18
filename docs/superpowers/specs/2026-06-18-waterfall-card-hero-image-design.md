# 首页瀑布流卡片配图设计

日期：2026-06-18

## 背景与目标

首页阅读视图的瀑布流由 `frontend/index.html` 中的 `#all-article-cards` 和
`#focus-tag-cards` 两个 `.card-grid` 容器组成，经 `frontend/app.js` 的
`renderCards()` 用 `#article-card-template` 渲染。当前卡片模板**没有任何图片
元素**，卡片只展示来源、日期、标题、摘要、徽章与标签。

目标：为**有配图**的文章卡片，在卡片顶部展示一张图片；当文章有多张图片时，
**只展示像素面积（宽×高）最大的那张**；**无配图**的文章保持现有纯文字样式不变。

## 现状要点

- 后端 `list_article_card_views`（`src/newspaper_translator/api/queries.py`）返回的
  `ArticleCardView` **已经有 `hero_image_url` 字段**，但目前被硬编码为 `None`
  （约第 1030 行）。
- `list_focus_tag_article_card_views` 复用 `list_article_card_views`，因此焦点标签
  瀑布流会自动跟随生效。
- 文章图片存于 `article_images` 表，仅有 `image_path`、`image_order` 两列，
  **未存宽高或文件大小**。已有 `list_article_images(article_id)` 可取某文章全部图片。
- 图片为磁盘上的绝对路径 JPG/PNG，通过 `/api/local-image?path=<绝对路径>` 提供
  （见 `src/newspaper_translator/web.py`）。
- 文章详情页已用 `images[0]` 作为 hero（取第一张，非最大）；本设计不改动详情页行为，
  仅聚焦首页卡片。
- 项目刻意保持依赖精简（`requirements.txt` 仅 4 项），**未安装 Pillow**。

## 设计决策

经确认采用：**按像素面积选最大 + 查询时实时计算 + 零新依赖 + 不改数据库**。

- 「最大」按像素面积 `width × height` 判定（最贴合「尺寸最大」字面意义）。
- 实时在卡片查询时计算：每页仅约 20 张卡片，每篇图片数量很少，只读图片文件头、
  不解码整图，开销可忽略；且对全部历史文章立即生效，无需数据库迁移或回填。
- 卡片布局采用「顶部大图（横幅式）」：图片铺满卡片顶部，文字在下方。

## 组件设计

### 1. 图片尺寸解析（新增纯函数模块）

新增 `src/newspaper_translator/image_dimensions.py`：

- `read_image_size(path: str) -> tuple[int, int] | None`
  - 只读文件头解析宽高，不解码整张图，零新依赖：
    - PNG：校验 8 字节签名后，从 IHDR 块读取宽、高（位于文件起始约 24 字节内）。
    - JPEG：扫描段标记，定位 SOF0/SOF1/SOF2（`0xFFC0/0xC1/0xC2`）帧头读取宽高。
  - 文件不存在、非图片、或头部无法解析 → 返回 `None`。
- `pick_largest_image(paths: list[str]) -> str | None`
  - 对每个路径调用 `read_image_size`，按 `width * height` 取最大者。
  - 解析失败的路径按面积 0 处理；当所有路径都解析失败但列表非空时，回退返回列表
    第一张（保证「有图就尽量出图」）。
  - 空列表 → 返回 `None`。

该模块为纯函数、无副作用、易测。

### 2. 后端卡片查询

修改 `list_article_card_views`（`api/queries.py`）：对每张卡片，
- 用已有 `list_article_images(database_url=..., article_id=...)` 取该文章全部图片路径；
- 调 `pick_largest_image(paths)` 得到最大图，赋给现有 `hero_image_url` 字段
  （替换当前硬编码的 `None`）。

沿用现有的 per-card 查询模式（与同一循环内的 `get_latest_article_enrichment`
N+1 模式一致），不引入新的架构层次。`list_focus_tag_article_card_views` 复用该函数，
自动生效。

### 3. 前端渲染

- `frontend/index.html`：在 `#article-card-template` 的 `<article class="article-card">`
  顶部新增一个图片元素 `<img class="card-hero" hidden>`（默认隐藏）。
- `frontend/app.js` 的 `renderCards()`：
  - 取卡片中的 `.card-hero` 元素；
  - 当 `card.hero_image_url` 存在时：
    设 `img.src = "/api/local-image?path=" + encodeURIComponent(card.hero_image_url)`，
    设 `img.loading = "lazy"`、`img.alt` 为标题，移除 `hidden`；
    绑定 `img.onerror` → 隐藏该图（磁盘缺图时不留破图标）。
  - 当无 `hero_image_url` 时：移除/隐藏该图片元素，卡片回到纯文字。
- `frontend/styles.css`：新增 `.card-hero` 样式——顶部满宽、固定高度（约 140px）、
  `object-fit: cover`、圆角与卡片顶部贴合（`.article-card` 需 `overflow: hidden`
  以裁切圆角）。

## 数据流

1. 前端请求文章卡片列表 → 后端 `list_article_card_views`。
2. 对每张卡片：查 `article_images` → `pick_largest_image` 读各图文件头比较面积 →
   选出最大图路径写入 `hero_image_url`（无可用图则为 `None`）。
3. 前端渲染卡片：有 `hero_image_url` → 顶部 `<img>` 经 `/api/local-image` 加载；
   无则纯文字。

## 错误处理

- 图片路径非绝对、磁盘文件不存在、或文件头无法解析：后端选图时按面积 0 跳过；
  若该文章全部图片都不可用，`hero_image_url` 为 `None`，卡片纯文字。
- 前端 `img.onerror` 兜底：即便后端返回了路径但实际加载失败（如运行环境路径差异），
  也隐藏该图，避免破图标。

## 测试（TDD）

- `read_image_size`：
  - 用小的真实 JPEG、PNG 夹具，断言返回正确宽高。
  - 损坏/非图片字节、空文件、不存在路径 → 返回 `None`。
- `pick_largest_image`：
  - 多图选面积最大者。
  - 含部分解析失败项时，仍从可解析者中选最大。
  - 全部解析失败但非空 → 回退返回第一张。
  - 空列表 → `None`。
- `list_article_card_views`：
  - 构造带多张不同尺寸图片的文章，断言 `hero_image_url` 为最大那张。
  - 无图文章 → `hero_image_url` 为 `None`。

## 不在本次范围（YAGNI）

- 不改详情页 `hero_image_url`/图库行为。
- 不新增数据库列、不做迁移或回填。
- 不引入图片处理依赖（如 Pillow）。
- 不实现真正的 Pinterest 等高错落 masonry 布局，沿用现有 `.card-grid`。
