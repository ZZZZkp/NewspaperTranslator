# 首页瀑布流卡片配图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首页瀑布流的文章卡片在有配图时于顶部展示一张图，多图时只展示像素面积最大的那张，无图文章保持纯文字。

**Architecture:** 新增一个零依赖的图片尺寸解析模块（只读 PNG/JPEG 文件头拿宽高），在 `list_article_card_views` 查询时为每张卡片挑选面积最大的图填入已有的 `hero_image_url` 字段；前端卡片模板加一个顶部 `<img>`，`renderCards()` 按 `hero_image_url` 渲染并对加载失败兜底。不改数据库、不加第三方依赖。

**Tech Stack:** Python 3（标准库）、SQLite、原生 JS/HTML/CSS、unittest/pytest。

**测试运行命令（全程统一）：** `PYTHONPATH=src ./.venv/bin/python -m pytest <路径> -v`

**设计文档：** `docs/superpowers/specs/2026-06-18-waterfall-card-hero-image-design.md`

---

### Task 1: 图片尺寸解析 `read_image_size`

只读文件头解析 PNG / JPEG 的宽高，零第三方依赖。

**Files:**
- Create: `src/newspaper_translator/image_dimensions.py`
- Test: `tests/test_image_dimensions.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_image_dimensions.py`：

```python
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from newspaper_translator.image_dimensions import read_image_size


def _png_bytes(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    return signature + ihdr


def _jpeg_bytes(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )


def _write(tmp: pathlib.Path, name: str, data: bytes) -> str:
    path = tmp / name
    path.write_bytes(data)
    return str(path)


class ReadImageSizeTests(unittest.TestCase):
    def test_reads_png_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "a.png", _png_bytes(640, 480))
            self.assertEqual(read_image_size(path), (640, 480))

    def test_reads_jpeg_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "a.jpg", _jpeg_bytes(800, 600))
            self.assertEqual(read_image_size(path), (800, 600))

    def test_returns_none_for_non_image_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            path = _write(tmp, "a.txt", b"not an image at all")
            self.assertIsNone(read_image_size(path))

    def test_returns_none_for_missing_file(self) -> None:
        self.assertIsNone(read_image_size("/nonexistent/path/missing.png"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_image_dimensions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newspaper_translator.image_dimensions'`

- [ ] **Step 3: Write minimal implementation**

创建 `src/newspaper_translator/image_dimensions.py`：

```python
"""Lightweight image header parsing (no third-party dependency).

Reads only the file header to obtain pixel dimensions for PNG and JPEG.
"""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_HEADER_READ_BYTES = 65536
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def read_image_size(path: str) -> tuple[int, int] | None:
    """Return (width, height) for a PNG/JPEG file, or None if unparseable."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_HEADER_READ_BYTES)
    except OSError:
        return None

    if data[:8] == _PNG_SIGNATURE:
        return _read_png_size(data)
    if data[:2] == b"\xff\xd8":
        return _read_jpeg_size(data)
    return None


def _read_png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _read_jpeg_size(data: bytes) -> tuple[int, int] | None:
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            if width <= 0 or height <= 0:
                return None
            return width, height
        if marker == 0xD8 or marker == 0xD9 or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        segment_length = int.from_bytes(data[index + 2 : index + 4], "big")
        if segment_length <= 0:
            return None
        index += 2 + segment_length
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_image_dimensions.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/image_dimensions.py tests/test_image_dimensions.py
git commit -m "feat: add zero-dependency PNG/JPEG header size reader"
```

---

### Task 2: 选最大图 `pick_largest_image`

按像素面积选最大；解析失败按面积 0；全失败但非空时回退第一张；空列表返回 None。

**Files:**
- Modify: `src/newspaper_translator/image_dimensions.py`
- Test: `tests/test_image_dimensions.py`

- [ ] **Step 1: Write the failing test**

在 `tests/test_image_dimensions.py` 顶部的 import 改为同时引入 `pick_largest_image`：

```python
from newspaper_translator.image_dimensions import pick_largest_image, read_image_size
```

并在文件末尾 `if __name__` 之前追加：

```python
class PickLargestImageTests(unittest.TestCase):
    def test_picks_largest_by_pixel_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            small = _write(tmp, "small.png", _png_bytes(100, 100))
            large = _write(tmp, "large.jpg", _jpeg_bytes(400, 300))
            self.assertEqual(pick_largest_image([small, large]), large)

    def test_ignores_unparseable_and_picks_largest_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            broken = _write(tmp, "broken.png", b"not an image")
            good = _write(tmp, "good.png", _png_bytes(50, 50))
            self.assertEqual(pick_largest_image([broken, good]), good)

    def test_falls_back_to_first_when_all_unparseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = pathlib.Path(tmp_dir)
            first = _write(tmp, "first.png", b"nope")
            second = _write(tmp, "second.png", b"nope either")
            self.assertEqual(pick_largest_image([first, second]), first)

    def test_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(pick_largest_image([]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_image_dimensions.py::PickLargestImageTests -v`
Expected: FAIL with `ImportError: cannot import name 'pick_largest_image'`

- [ ] **Step 3: Write minimal implementation**

在 `src/newspaper_translator/image_dimensions.py` 末尾追加：

```python
def pick_largest_image(paths: list[str]) -> str | None:
    """Return the path whose pixel area (width*height) is largest.

    Paths that cannot be parsed count as area 0. When every path is
    unparseable but the list is non-empty, fall back to the first path so a
    card with images still shows one. Returns None for an empty list.
    """
    if not paths:
        return None

    best_path = paths[0]
    best_area = -1
    for path in paths:
        size = read_image_size(path)
        area = size[0] * size[1] if size is not None else 0
        if area > best_area:
            best_area = area
            best_path = path
    return best_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_image_dimensions.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/image_dimensions.py tests/test_image_dimensions.py
git commit -m "feat: add pick_largest_image by pixel area with fallback"
```

---

### Task 3: 卡片查询填充 `hero_image_url`

在 `list_article_card_views` 中为每张卡片挑出最大图，写入现有 `hero_image_url`。

**Files:**
- Modify: `src/newspaper_translator/api/queries.py`（import 区 + 约第 1019-1034 行的卡片组装）
- Test: `tests/test_api_queries.py`

- [ ] **Step 1: Write the failing test**

在 `tests/test_api_queries.py` 的 `ApiQueriesTests`（与 `test_article_detail_returns_local_images_and_clean_body` 同一个测试类）内追加以下方法。它复用已有的 `_insert_document` 与 `_build_parse_result`，并在文章正文里嵌入两个绝对路径图片（一大一小），断言卡片选中的是面积更大的那张：

```python
    def test_article_cards_set_hero_image_to_largest_image(self) -> None:
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            database_path = temp_path / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            small_image = temp_path / "small.png"
            small_image.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
                + (100).to_bytes(4, "big")
                + (100).to_bytes(4, "big")
                + b"\x08\x02\x00\x00\x00"
            )
            large_image = temp_path / "large.png"
            large_image.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
                + (800).to_bytes(4, "big")
                + (600).to_bytes(4, "big")
                + b"\x08\x02\x00\x00\x00"
            )

            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Two images, pick the larger one",
                    body_suffix=(
                        f"![]({small_image})\n"
                        f"![]({large_image})"
                    ),
                ),
                document_key=document_key,
                publication_date="2026-04-22",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )

            cards = list_article_card_views(database_url=database_url)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].hero_image_url, str(large_image))

    def test_article_cards_have_no_hero_image_without_images(self) -> None:
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-23.pdf",
                source_name="Financial Times",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-23",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="No images here",
                    body_suffix="Just plain text, no figures.",
                ),
                document_key=document_key,
                publication_date="2026-04-23",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )

            cards = list_article_card_views(database_url=database_url)

        self.assertEqual(len(cards), 1)
        self.assertIsNone(cards[0].hero_image_url)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest "tests/test_api_queries.py::ApiQueriesTests::test_article_cards_set_hero_image_to_largest_image" -v`
Expected: FAIL — `AssertionError: None != '.../large.png'`（当前 `hero_image_url` 硬编码为 `None`）

- [ ] **Step 3: Add the import**

在 `src/newspaper_translator/api/queries.py` 顶部 import 区（紧接 `from newspaper_translator.document_processing import (...)` 之后）新增：

```python
from newspaper_translator.image_dimensions import pick_largest_image
```

- [ ] **Step 4: Compute hero image in the card loop**

在 `list_article_card_views` 的 `for row in rows:` 循环里，把构造 `ArticleCardView` 前的代码改为先算出最大图。找到这段（约第 1011-1034 行）：

```python
        if enrichment is not None:
            title_zh = enrichment.translated_title_zh
            summary_zh = enrichment.summary_zh
            tags = enrichment.tags
            reading_status = "ready"
            if enrichment.status == "partial":
                processing_badges.append("partial_enrichment")

        cards.append(
            ArticleCardView(
                article_id=row[0],
                document_key=row[1],
                source_name=row[2],
                publication_date=row[3],
                page_label="",
                title_en=row[4],
                title_zh=title_zh,
                summary_zh=summary_zh,
                tags=tags,
                hero_image_url=None,
                reading_status=reading_status,
                quality_flags=[],
                processing_badges=processing_badges,
            )
        )
```

改为：

```python
        if enrichment is not None:
            title_zh = enrichment.translated_title_zh
            summary_zh = enrichment.summary_zh
            tags = enrichment.tags
            reading_status = "ready"
            if enrichment.status == "partial":
                processing_badges.append("partial_enrichment")

        image_paths = [
            image.image_path
            for image in list_article_images(
                database_url=database_url,
                article_id=row[0],
            )
        ]
        hero_image_url = pick_largest_image(image_paths)

        cards.append(
            ArticleCardView(
                article_id=row[0],
                document_key=row[1],
                source_name=row[2],
                publication_date=row[3],
                page_label="",
                title_en=row[4],
                title_zh=title_zh,
                summary_zh=summary_zh,
                tags=tags,
                hero_image_url=hero_image_url,
                reading_status=reading_status,
                quality_flags=[],
                processing_badges=processing_badges,
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_api_queries.py -v`
Expected: PASS（含两个新用例，且原有用例不回归）

- [ ] **Step 6: Commit**

```bash
git add src/newspaper_translator/api/queries.py tests/test_api_queries.py
git commit -m "feat: set article card hero_image_url to largest image"
```

---

### Task 4: 前端卡片顶部配图

卡片模板加顶部 `<img>`，`renderCards()` 按 `hero_image_url` 渲染并对加载失败兜底，CSS 控制外观。

**Files:**
- Modify: `frontend/index.html`（`#article-card-template`，约第 428-439 行）
- Modify: `frontend/app.js`（`renderCards()`，约第 381-417 行）
- Modify: `frontend/styles.css`（新增 `.card-hero`，并给 `.article-card` 加 `overflow: hidden`）
- Test: `tests/test_frontend_static.py`

- [ ] **Step 1: Write the failing test**

在 `tests/test_frontend_static.py` 的 `FrontendStaticTests` 类内追加：

```python
    def test_article_card_template_includes_hero_image(self) -> None:
        index_path = PROJECT_ROOT / "frontend" / "index.html"
        index_text = index_path.read_text()
        self.assertIn('class="card-hero"', index_text)

        styles_path = PROJECT_ROOT / "frontend" / "styles.css"
        self.assertIn(".card-hero", styles_path.read_text())

        app_path = PROJECT_ROOT / "frontend" / "app.js"
        self.assertIn("hero_image_url", app_path.read_text())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest "tests/test_frontend_static.py::FrontendStaticTests::test_article_card_template_includes_hero_image" -v`
Expected: FAIL — `AssertionError: 'class="card-hero"' not found`

- [ ] **Step 3: Add the image element to the card template**

在 `frontend/index.html` 把 `#article-card-template` 内的 `<article>` 起始部分：

```html
    <template id="article-card-template">
      <article class="article-card">
        <div class="card-topline">
```

改为（在 `card-topline` 之前插入一个默认隐藏的图片）：

```html
    <template id="article-card-template">
      <article class="article-card">
        <img class="card-hero" alt="" hidden />
        <div class="card-topline">
```

- [ ] **Step 4: Render the hero image in renderCards()**

在 `frontend/app.js` 的 `renderCards()` 里，找到这段（约第 382-389 行）：

```javascript
    const node = articleCardTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.articleId = card.article_id;
    node.querySelector(".card-source").textContent = card.source_name;
    node.querySelector(".card-date").textContent = card.publication_date;
    node.querySelector(".card-title").textContent = card.title_zh || card.title_en;
    node.querySelector(".card-summary").textContent =
      card.summary_zh || "当前没有中文摘要，已降级为英文阅读模式。";
```

在其后紧接着插入 hero 图渲染逻辑：

```javascript
    const hero = node.querySelector(".card-hero");
    if (hero) {
      if (card.hero_image_url) {
        hero.src = `/api/local-image?path=${encodeURIComponent(card.hero_image_url)}`;
        hero.alt = card.title_zh || card.title_en || "article image";
        hero.loading = "lazy";
        hero.hidden = false;
        hero.addEventListener("error", () => {
          hero.remove();
        });
      } else {
        hero.remove();
      }
    }
```

- [ ] **Step 5: Add the CSS**

`.article-card` 规则块（约第 289 行）当前为 `padding: 20px; border-radius: 20px;` 且**没有** `overflow: hidden;`。先给它加上 `overflow: hidden;`（让满宽图片的圆角随卡片裁切）。找到：

```css
.article-card {
  position: relative;
  display: grid;
  gap: 12px;
  padding: 20px;
  border-radius: 20px;
  background: var(--surface-strong);
  border: 1px solid rgba(221, 209, 189, 0.8);
  cursor: pointer;
}
```

改为（仅新增一行 `overflow: hidden;`）：

```css
.article-card {
  position: relative;
  display: grid;
  gap: 12px;
  padding: 20px;
  border-radius: 20px;
  background: var(--surface-strong);
  border: 1px solid rgba(221, 209, 189, 0.8);
  cursor: pointer;
  overflow: hidden;
}
```

然后在该规则块之后新增 `.card-hero` 样式。卡片有 `padding: 20px`，用等量负外边距让图片满宽铺到卡片顶部边缘：

```css
.card-hero {
  width: calc(100% + 40px);
  height: 160px;
  margin: -20px -20px 0;
  object-fit: cover;
  border-radius: 20px 20px 0 0;
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_frontend_static.py -v`
Expected: PASS（含新用例）

- [ ] **Step 7: Manual smoke check (optional but recommended)**

若本地能起前端，打开首页瀑布流，确认：有配图文章卡片顶部出现一张图、多图文章显示最大那张、无配图文章为纯文字、磁盘缺图不留破图标。

- [ ] **Step 8: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_frontend_static.py
git commit -m "feat: show largest article image at top of waterfall cards"
```

---

## 完成后

运行完整测试套件确认无回归：

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest tests/test_image_dimensions.py tests/test_api_queries.py tests/test_frontend_static.py -v
```

Expected: 全部 PASS。
