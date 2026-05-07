# Article Throughput And Advertisement Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise article enrichment throughput and add an advertisement filter that piggybacks on the existing translation request, while keeping reader surfaces clean and operator views fully traceable.

**Architecture:**
1. Persist new classification metadata (`content_type`, `classification_reason`) on `article_enrichment_outputs`, and treat `skipped_advertisement` as a usable terminal status on `article_enrichment_runs`.
2. Change `GeminiArticleTranslator` to return `content_type` plus translation; branch `enrich_article()` so advertisements skip the summary/tagger stage and finalize as `skipped_advertisement`.
3. Restructure the worker loop so the article tick can claim more items than concurrency, do an active/idle poll cadence, and skip writing `scheduler_runs` on empty-queue ticks.
4. Filter `skipped_advertisement` out of reader-facing API surfaces while keeping it visible in operator processing detail views.

**Tech Stack:** Python 3, SQLite, sequential SQL migrations under `src/newspaper_translator/migrations/`, `unittest`, `concurrent.futures.ThreadPoolExecutor`.

**Spec:** `docs/superpowers/specs/2026-05-06-article-throughput-and-ad-filter-design.md`

---

## File Map

**Created:**
- `src/newspaper_translator/migrations/0012_article_enrichment_classification.sql` — adds `content_type` and `classification_reason` columns to `article_enrichment_outputs`.

**Modified:**
- `src/newspaper_translator/gemini.py` — extends `ArticleTranslationResult` to carry `content_type` and `classification_reason`; updates the translator prompt and JSON parsing to handle `article` / `advertisement` / `uncertain` payloads.
- `src/newspaper_translator/article_store.py` — `record_article_enrichment_outputs` accepts and writes `content_type` + `classification_reason`; `LatestArticleEnrichment` exposes these fields and `get_latest_article_enrichment` includes `skipped_advertisement` rows.
- `src/newspaper_translator/article_enrichment.py` — branches after the translator call; advertisements skip the summary/tagger and finalize as `skipped_advertisement`.
- `src/newspaper_translator/document_processing.py` — adds `process_one_article_concurrency`, splits the article tick so batch size can exceed concurrency, adds a no-op `run_processing_tick_if_work_available` path that writes no scheduler row when both queues are empty.
- `src/newspaper_translator/worker.py` — reads new env settings (`ARTICLE_WORKER_BATCH_SIZE`, `PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS`, `PROCESSING_IDLE_POLL_INTERVAL_SECONDS`), default article concurrency becomes `4`, loop alternates active/idle interval based on whether the tick did real work.
- `src/newspaper_translator/api/queries.py` — reader-facing list and overview queries exclude articles whose latest enrichment is `skipped_advertisement`; operator processing detail view exposes `content_type` / `classification_reason` / `skipped_advertisement` as a usable status.
- `docker-compose.yml` — passes the new worker concurrency, batch size, and poll interval env vars through to the `worker` service.
- `.env.example` — documents the new env vars.

**Modified tests:**
- `tests/test_gemini.py` — updates the existing translator tests for the new response shape; adds tests for `advertisement` and `uncertain` shapes and for failure on missing fields.
- `tests/test_article_enrichment.py` — adds advertisement/uncertain enrichment tests; updates `_FakeTranslator` and friends to return `content_type`.
- `tests/test_article_store.py` — covers new `content_type` / `classification_reason` persistence and that `get_latest_article_enrichment` returns `skipped_advertisement` rows.
- `tests/test_document_processing.py` — covers batched-but-bounded article concurrency and the "no scheduler row when queues are empty" behavior.
- `tests/test_worker.py` — covers active vs idle interval cadence and that the new env vars wire through.
- `tests/test_api_queries.py` — covers reader exclusion of `skipped_advertisement` and operator inclusion.
- `tests/test_database.py` — sanity check that the new columns exist after migrations.

---

## Pre-flight

- [ ] **Step 0a: Confirm the baseline test suite is green on the current branch**

```bash
cd /Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator
./.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
```

Expected: ends with `OK` (no failures, no errors). If anything is already broken, stop and surface it before starting Task 1.

- [ ] **Step 0b: Confirm the migration sequence and the relevant call sites still match the plan**

```bash
ls src/newspaper_translator/migrations
grep -n "def record_article_enrichment_outputs\|def get_latest_article_enrichment\|def find_successful_article_enrichment_by_article_key_and_input_hash" src/newspaper_translator/article_store.py
grep -n "def enrich_article\|def __call__" src/newspaper_translator/article_enrichment.py src/newspaper_translator/gemini.py
grep -n "list_eligible_article_processing_runs\|run_processing_tick" src/newspaper_translator/document_processing.py
```

Expected: highest existing migration is `0011_drop_processing_tasks.sql` (next is `0012`), and the listed function definitions exist where the plan references them.

---

## Task 1: Add classification columns to `article_enrichment_outputs`

**Files:**
- Create: `src/newspaper_translator/migrations/0012_article_enrichment_classification.sql`
- Test: `tests/test_database.py`

- [ ] **Step 1.1: Write the failing migration assertion**

Append the following test method to the most appropriate `*Tests` class in `tests/test_database.py` (look for a class that already covers schema column presence; if there is none, add the new class at the bottom of the file before `if __name__ == "__main__":`).

```python
    def test_article_enrichment_outputs_has_classification_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            connection = sqlite3.connect(database_path)
            try:
                columns = [
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(article_enrichment_outputs)"
                    ).fetchall()
                ]
            finally:
                connection.close()

        self.assertIn("content_type", columns)
        self.assertIn("classification_reason", columns)
```

If `tempfile`, `pathlib`, `sqlite3`, or `run_pending_migrations` are not yet imported in this test file, add the imports at the top of the file (mirror the imports already in use elsewhere in the test suite, e.g. `tests/test_worker.py`).

- [ ] **Step 1.2: Run the test to verify it fails**

```bash
./.venv/bin/python -m unittest tests.test_database -v 2>&1 | tail -20
```

Expected: FAIL on `test_article_enrichment_outputs_has_classification_columns` because the columns do not exist yet.

- [ ] **Step 1.3: Add the migration file**

Create `src/newspaper_translator/migrations/0012_article_enrichment_classification.sql`:

```sql
ALTER TABLE article_enrichment_outputs
    ADD COLUMN content_type TEXT NOT NULL DEFAULT 'article';

ALTER TABLE article_enrichment_outputs
    ADD COLUMN classification_reason TEXT NOT NULL DEFAULT '';
```

(Existing rows pick up the defaults automatically. We do not add a CHECK constraint; SQLite already stores `article_enrichment_runs.status` as free-form TEXT, so `skipped_advertisement` is accepted without schema changes.)

- [ ] **Step 1.4: Run the test to verify it passes**

```bash
./.venv/bin/python -m unittest tests.test_database -v 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add src/newspaper_translator/migrations/0012_article_enrichment_classification.sql tests/test_database.py
git commit -m "Add content_type and classification_reason to enrichment outputs"
```

---

## Task 2: Persist classification metadata in `article_store`

**Files:**
- Modify: `src/newspaper_translator/article_store.py:82-115` (`LatestArticleEnrichment`), `src/newspaper_translator/article_store.py:697-790` (`record_article_enrichment_outputs`), `src/newspaper_translator/article_store.py:792-861` (`get_latest_article_enrichment`)
- Test: `tests/test_article_store.py`

### Step 2.1: Failing test for `record_article_enrichment_outputs` writing classification fields

- [ ] **Step 2.1: Write the failing test**

Add the following test method inside `tests/test_article_store.py`. Use the same class that contains existing enrichment-output tests; if uncertain which class, place it next to the most similar test and add it as a sibling method.

```python
    def test_records_content_type_and_classification_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            article = self._create_article(database_url=database_url)

            run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=article.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=run.enrichment_run_id,
                translated_title_zh=None,
                summary_zh=None,
                translated_body_zh=None,
                translation_status="skipped",
                summary_status="skipped",
                tagging_status="skipped",
                tags=[],
                content_type="advertisement",
                classification_reason="Display ad for jewelry retailer.",
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=run.enrichment_run_id,
                status="skipped_advertisement",
            )

            latest = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(latest.status, "skipped_advertisement")
        self.assertEqual(latest.content_type, "advertisement")
        self.assertEqual(
            latest.classification_reason,
            "Display ad for jewelry retailer.",
        )
```

If `_create_article` does not already exist in the test class, copy the helper used by the closest existing enrichment test (search for `create_parse_run` near the top of `tests/test_article_store.py` and reuse its setup pattern). The helper should return a `StoredFinalArticle`.

- [ ] **Step 2.2: Run the test to verify it fails**

```bash
./.venv/bin/python -m unittest tests.test_article_store -v 2>&1 | tail -25
```

Expected: FAIL — the new keyword arguments `content_type` and `classification_reason` are not accepted by `record_article_enrichment_outputs`, and `LatestArticleEnrichment` has no such fields.

- [ ] **Step 2.3: Extend `LatestArticleEnrichment` with the new fields**

In `src/newspaper_translator/article_store.py`, update the `LatestArticleEnrichment` dataclass (currently at line 96):

```python
@dataclass(frozen=True)
class LatestArticleEnrichment:
    enrichment_run_id: str
    article_id: str
    parse_run_id: str
    status: str
    provider_name: str
    model_name: str
    prompt_version: str
    input_hash: str
    translated_title_zh: str | None
    summary_zh: str | None
    translated_body_zh: str | None
    translation_status: str
    summary_status: str
    tagging_status: str
    content_type: str
    classification_reason: str
    tags: list[str]
    started_at: str
    finished_at: str | None
```

- [ ] **Step 2.4: Update `record_article_enrichment_outputs` to accept and persist the new fields**

Replace the body of `record_article_enrichment_outputs` (currently at line 697):

```python
def record_article_enrichment_outputs(
    *,
    database_url: str,
    enrichment_run_id: str,
    translated_title_zh: str | None,
    summary_zh: str | None,
    translated_body_zh: str | None,
    translation_status: str,
    summary_status: str,
    tagging_status: str,
    tags: list[str],
    content_type: str = "article",
    classification_reason: str = "",
) -> None:
    if translation_status == "succeeded":
        if not (translated_title_zh or "").strip() or not (translated_body_zh or "").strip():
            raise ValueError("Successful translation output requires Chinese title and body text")
    if summary_status == "succeeded" and not (summary_zh or "").strip():
        raise ValueError("Successful summary output requires non-empty summary_zh")
    if tagging_status == "succeeded" and not 3 <= len(tags) <= 8:
        raise ValueError("Successful tagging output must produce 3 to 8 tags")
    if content_type not in ("article", "advertisement", "uncertain"):
        raise ValueError(
            f"Unsupported content_type for enrichment output: {content_type!r}"
        )

    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO article_enrichment_outputs (
                enrichment_run_id,
                translated_title_zh,
                summary_zh,
                translated_body_zh,
                translation_status,
                summary_status,
                tagging_status,
                content_type,
                classification_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enrichment_run_id,
                translated_title_zh,
                summary_zh,
                translated_body_zh,
                translation_status,
                summary_status,
                tagging_status,
                content_type,
                classification_reason,
            ),
        )
        for index, tag in enumerate(tags, start=1):
            connection.execute(
                """
                INSERT INTO article_tags (
                    article_tag_id,
                    enrichment_run_id,
                    tag_text,
                    tag_order
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    enrichment_run_id,
                    tag,
                    index,
                ),
            )
        connection.commit()
    finally:
        connection.close()
```

- [ ] **Step 2.5: Update `get_latest_article_enrichment` to read the new fields and include `skipped_advertisement`**

Replace the body of `get_latest_article_enrichment` (currently at line 792). The two changes are: (a) include `skipped_advertisement` in the WHERE clause, (b) select and return the new columns.

```python
def get_latest_article_enrichment(
    *,
    database_url: str,
    article_id: str,
) -> LatestArticleEnrichment:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                r.enrichment_run_id,
                r.article_id,
                r.parse_run_id,
                r.status,
                r.provider_name,
                r.model_name,
                r.prompt_version,
                r.input_hash,
                o.translated_title_zh,
                o.summary_zh,
                o.translated_body_zh,
                o.translation_status,
                o.summary_status,
                o.tagging_status,
                o.content_type,
                o.classification_reason,
                r.started_at,
                r.finished_at
            FROM article_enrichment_runs r
            LEFT JOIN article_enrichment_outputs o
                ON o.enrichment_run_id = r.enrichment_run_id
            WHERE r.article_id = ?
                AND r.status IN ('partial', 'succeeded', 'skipped_advertisement')
            ORDER BY r.finished_at DESC, r.rowid DESC
            LIMIT 1
            """,
            (article_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"No usable enrichment run found for article: {article_id}")
        tag_rows = connection.execute(
            """
            SELECT tag_text
            FROM article_tags
            WHERE enrichment_run_id = ?
            ORDER BY tag_order ASC
            """,
            (row[0],),
        ).fetchall()
    finally:
        connection.close()

    return LatestArticleEnrichment(
        enrichment_run_id=row[0],
        article_id=row[1],
        parse_run_id=row[2],
        status=row[3],
        provider_name=row[4],
        model_name=row[5],
        prompt_version=row[6],
        input_hash=row[7],
        translated_title_zh=row[8],
        summary_zh=row[9],
        translated_body_zh=row[10],
        translation_status=row[11],
        summary_status=row[12],
        tagging_status=row[13],
        content_type=row[14] if row[14] is not None else "article",
        classification_reason=row[15] if row[15] is not None else "",
        tags=[tag_row[0] for tag_row in tag_rows],
        started_at=row[16],
        finished_at=row[17],
    )
```

(The `row[14]` / `row[15]` `None`-coalesce keeps backwards compatibility for old rows whose `LEFT JOIN` produced no output row.)

- [ ] **Step 2.6: Run the test to verify it passes**

```bash
./.venv/bin/python -m unittest tests.test_article_store -v 2>&1 | tail -25
```

Expected: PASS.

- [ ] **Step 2.7: Run the broader article-store test module to confirm no regressions**

```bash
./.venv/bin/python -m unittest tests.test_article_store 2>&1 | tail -5
```

Expected: `OK`.

- [ ] **Step 2.8: Commit**

```bash
git add src/newspaper_translator/article_store.py tests/test_article_store.py
git commit -m "Persist content_type and classification_reason on enrichment outputs"
```

---

## Task 3: Translator returns content_type plus translation

**Files:**
- Modify: `src/newspaper_translator/gemini.py:18-22` (`ArticleTranslationResult`), `src/newspaper_translator/gemini.py:123-179` (`GeminiArticleTranslator`)
- Test: `tests/test_gemini.py`

- [ ] **Step 3.1: Write the failing tests for the new translator response shape**

Add the following test methods inside `class GeminiArticleTranslatorTests` in `tests/test_gemini.py`:

```python
    def test_returns_classification_for_normal_article(self) -> None:
        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "content_type": "article",
                                            "classification_reason": "Regular newspaper coverage.",
                                            "translated_title_zh": "测试标题",
                                            "translated_body_zh": "正文",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(api_token="t", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        result = translator(self._minimal_article())

        self.assertEqual(result.content_type, "article")
        self.assertEqual(result.classification_reason, "Regular newspaper coverage.")
        self.assertEqual(result.translated_title_zh, "测试标题")
        self.assertEqual(result.translated_body_zh, "正文")

    def test_allows_empty_translation_for_advertisement(self) -> None:
        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "content_type": "advertisement",
                                            "classification_reason": "Display ad block.",
                                            "translated_title_zh": "",
                                            "translated_body_zh": "",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(api_token="t", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        result = translator(self._minimal_article())

        self.assertEqual(result.content_type, "advertisement")
        self.assertEqual(result.translated_title_zh, "")
        self.assertEqual(result.translated_body_zh, "")

    def test_treats_uncertain_as_translation_required(self) -> None:
        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "content_type": "uncertain",
                                            "classification_reason": "Borderline case.",
                                            "translated_title_zh": "标题",
                                            "translated_body_zh": "正文",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(api_token="t", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        result = translator(self._minimal_article())

        self.assertEqual(result.content_type, "uncertain")
        self.assertEqual(result.translated_title_zh, "标题")

    def test_rejects_article_with_missing_translation(self) -> None:
        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "content_type": "article",
                                            "classification_reason": "",
                                            "translated_title_zh": "",
                                            "translated_body_zh": "",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(api_token="t", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        with self.assertRaises(GeminiError):
            translator(self._minimal_article())

    def test_rejects_unknown_content_type(self) -> None:
        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "content_type": "promo",
                                            "classification_reason": "",
                                            "translated_title_zh": "标题",
                                            "translated_body_zh": "正文",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(api_token="t", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        with self.assertRaises(GeminiError):
            translator(self._minimal_article())

    def _minimal_article(self) -> "StoredFinalArticle":
        return StoredFinalArticle(
            article_id="article-1",
            parse_run_id="parse-run-1",
            document_key="message-1:attachment-1:hash-1",
            publication_date="2026-04-20",
            article_order=1,
            primary_source_order=1,
            source_fragment_count=1,
            title_en="Headline",
            body_text_en="Body.",
            created_at="2026-04-28 00:00:00",
        )
```

If `GeminiError` is not already imported into the test module, add it to the existing imports from `newspaper_translator.gemini`.

Also update the two existing translator tests (around `tests/test_gemini.py:307` and `tests/test_gemini.py:377`) so the JSON response payloads include `"content_type": "article"` and `"classification_reason": "..."` — those tests will start failing once Step 3.3 lands and they must continue to pass.

```python
                                        {
                                            "content_type": "article",
                                            "classification_reason": "Regular newspaper article, not an advertisement.",
                                            "translated_title_zh": "大型石油公司远赴他处避开中东动荡",
                                            "translated_body_zh": "多家能源企业正加速在非洲和南美寻找新机会。",
                                        }
```

(Apply the same shape to the OpenAI-compatible test fixture as well.)

- [ ] **Step 3.2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m unittest tests.test_gemini -v 2>&1 | tail -30
```

Expected: FAIL. The new tests fail because `ArticleTranslationResult` does not have `content_type` / `classification_reason`, and the parser does not validate those fields.

- [ ] **Step 3.3: Update `ArticleTranslationResult` and `GeminiArticleTranslator`**

In `src/newspaper_translator/gemini.py`, replace the `ArticleTranslationResult` dataclass at line 18:

```python
@dataclass(frozen=True)
class ArticleTranslationResult:
    content_type: str
    classification_reason: str
    translated_title_zh: str
    translated_body_zh: str
```

Replace the body of `GeminiArticleTranslator.__call__` (currently at line 133) and `_build_prompt` (currently at line 165) with:

```python
    def __call__(self, article: StoredFinalArticle) -> ArticleTranslationResult:
        payload = _build_request_payload(
            settings=self._settings,
            prompt=self._build_prompt(article),
        )
        response = self._transport.request(
            method="POST",
            url=_build_generate_content_url(self._settings),
            headers=_build_request_headers(self._settings),
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._settings.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise GeminiError(f"Gemini request failed with status {response.status_code}")

        try:
            result = json.loads(_extract_response_text(response.body))
            content_type = result["content_type"]
            classification_reason = result["classification_reason"]
            translated_title_zh = result["translated_title_zh"]
            translated_body_zh = result["translated_body_zh"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini response did not contain a valid translation payload") from exc

        if content_type not in ("article", "advertisement", "uncertain"):
            raise GeminiError(
                f"Gemini translation payload has unsupported content_type: {content_type!r}"
            )
        if not isinstance(classification_reason, str):
            raise GeminiError("Gemini translation payload classification_reason must be a string")
        if not isinstance(translated_title_zh, str) or not isinstance(translated_body_zh, str):
            raise GeminiError("Gemini translation payload must include string title and body fields")

        if content_type in ("article", "uncertain"):
            if not translated_title_zh.strip() or not translated_body_zh.strip():
                raise GeminiError(
                    "Gemini translation payload must include translated_title_zh and translated_body_zh"
                )

        return ArticleTranslationResult(
            content_type=content_type,
            classification_reason=classification_reason.strip(),
            translated_title_zh=translated_title_zh.strip(),
            translated_body_zh=translated_body_zh.strip(),
        )

    def _build_prompt(self, article: StoredFinalArticle) -> str:
        return (
            "You are translating English newspaper content into Simplified Chinese AND classifying it. "
            "The source text is parsed from a printed newspaper page. "
            "Most parsed items are normal newspaper content and must be classified as \"article\". "
            "Only classify content as \"advertisement\" when it is very obviously a newspaper "
            "advertisement, sponsored or promotional block, subscription offer, display ad, or "
            "advertorial block. Business news, market coverage, product reporting, reviews, opinion "
            "columns, book reviews, real-estate reporting, job-market reporting, and company profiles "
            "are NOT advertisements just because they mention companies, products, prices, or services. "
            "When you are not sure, classify as \"uncertain\" and still provide the translation. "
            "return JSON only. "
            "Do not use Markdown code fences. "
            "Do not include explanations outside the JSON. "
            'Return exactly these fields: '
            '{"content_type":"article|advertisement|uncertain",'
            '"classification_reason":"...",'
            '"translated_title_zh":"...",'
            '"translated_body_zh":"..."}. '
            "For \"article\" or \"uncertain\", translated_title_zh and translated_body_zh must be non-empty. "
            "For \"advertisement\", translated_title_zh and translated_body_zh may be empty strings. "
            "Preserve continuation markers and jump words exactly when they appear in the source, "
            'such as "Please turn to page A7" or "Continued from Page One". '
            "Do not silently remove, summarize, or normalize those navigation markers. "
            "Preserve meaning rather than literal word order.\n\n"
            f"Title:\n{article.title_en}\n\n"
            f"Body:\n{article.body_text_en}\n"
        )
```

- [ ] **Step 3.4: Run the tests to verify they pass**

```bash
./.venv/bin/python -m unittest tests.test_gemini -v 2>&1 | tail -25
```

Expected: PASS for all `GeminiArticleTranslatorTests`.

- [ ] **Step 3.5: Commit**

```bash
git add src/newspaper_translator/gemini.py tests/test_gemini.py
git commit -m "Return content_type and classification_reason from translator"
```

---

## Task 4: Branch enrichment flow on classification

**Files:**
- Modify: `src/newspaper_translator/article_enrichment.py:15-104` (`enrich_article`)
- Test: `tests/test_article_enrichment.py`

- [ ] **Step 4.1: Update existing fakes to return content_type**

In `tests/test_article_enrichment.py`, update `_FakeTranslator`, `_CountingTranslator`, and `_CapturingTranslator` so each returned `ArticleTranslationResult` includes `content_type="article"` and `classification_reason="Regular newspaper article."` Replace each constructor call with:

```python
        return ArticleTranslationResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
        )
```

- [ ] **Step 4.2: Add the failing advertisement-flow test**

Add the following test method inside `class ArticleEnrichmentTests` in `tests/test_article_enrichment.py`:

```python
    def test_marks_advertisement_classifications_as_skipped_advertisement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Diamond Sale Today",
                    body_suffix="50% off all jewelry, this weekend only.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            summarizer = _CountingSummarizerTagger()
            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                translator=_AdvertisementTranslator(),
                summarizer_tagger=summarizer,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
            )
            latest = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(run.status, "skipped_advertisement")
        self.assertEqual(summarizer.call_count, 0)
        self.assertEqual(latest.content_type, "advertisement")
        self.assertEqual(latest.translation_status, "skipped")
        self.assertEqual(latest.summary_status, "skipped")
        self.assertEqual(latest.tagging_status, "skipped")
        self.assertEqual(latest.tags, [])
```

Add the helper translator at the bottom of the file alongside the other fakes:

```python
class _AdvertisementTranslator:
    def __call__(self, article):
        return ArticleTranslationResult(
            content_type="advertisement",
            classification_reason="Display ad for jewelry retailer.",
            translated_title_zh="",
            translated_body_zh="",
        )
```

- [ ] **Step 4.3: Add the failing uncertain-flow test (still translates and summarizes)**

Add immediately below the previous test:

```python
    def test_uncertain_classifications_continue_with_summary_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Borderline Headline",
                    body_suffix="Some body text.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            summarizer = _CountingSummarizerTagger()
            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                translator=_UncertainTranslator(),
                summarizer_tagger=summarizer,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
            )
            latest = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(summarizer.call_count, 1)
        self.assertEqual(latest.content_type, "uncertain")
        self.assertEqual(latest.translation_status, "succeeded")
        self.assertEqual(latest.summary_status, "succeeded")
        self.assertEqual(latest.tagging_status, "succeeded")
```

Add the helper at the bottom of the file:

```python
class _UncertainTranslator:
    def __call__(self, article):
        return ArticleTranslationResult(
            content_type="uncertain",
            classification_reason="Borderline newspaper item.",
            translated_title_zh="不确定标题",
            translated_body_zh="不确定正文。",
        )
```

- [ ] **Step 4.4: Run the new tests to verify they fail**

```bash
./.venv/bin/python -m unittest tests.test_article_enrichment -v 2>&1 | tail -30
```

Expected: FAIL on the two new tests; existing tests should still pass after Step 4.1's fake-translator updates.

- [ ] **Step 4.5: Update `enrich_article` to branch on content_type**

Replace the body of `enrich_article` in `src/newspaper_translator/article_enrichment.py`:

```python
def enrich_article(
    *,
    database_url: str,
    article_id: str,
    translator,
    summarizer_tagger,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    force_reenrich: bool = False,
) -> ArticleEnrichmentRun:
    article = get_final_article(
        database_url=database_url,
        article_id=article_id,
    )
    input_hash = build_article_input_hash(article)
    if not force_reenrich:
        reusable_run = find_successful_article_enrichment_by_article_key_and_input_hash(
            database_url=database_url,
            article_key=article.article_key,
            input_hash=input_hash,
        )
        if reusable_run is not None:
            return reusable_run
    enrichment_run = create_article_enrichment_run(
        database_url=database_url,
        article_id=article.article_id,
        parse_run_id=article.parse_run_id,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        input_hash=input_hash,
    )

    try:
        translation = translator(article)
        if translation.content_type == "advertisement":
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                translated_title_zh=None,
                summary_zh=None,
                translated_body_zh=None,
                translation_status="skipped",
                summary_status="skipped",
                tagging_status="skipped",
                tags=[],
                content_type="advertisement",
                classification_reason=translation.classification_reason,
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="skipped_advertisement",
            )
        else:
            try:
                summary_and_tags = summarizer_tagger(
                    article=article,
                    translated_title_zh=translation.translated_title_zh,
                    translated_body_zh=translation.translated_body_zh,
                )
            except Exception as exc:
                record_article_enrichment_outputs(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    translated_title_zh=translation.translated_title_zh,
                    summary_zh=None,
                    translated_body_zh=translation.translated_body_zh,
                    translation_status="succeeded",
                    summary_status="failed",
                    tagging_status="failed",
                    tags=[],
                    content_type=translation.content_type,
                    classification_reason=translation.classification_reason,
                )
                finalize_article_enrichment_run(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    status="partial",
                    error_message=str(exc),
                )
            else:
                record_article_enrichment_outputs(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    translated_title_zh=translation.translated_title_zh,
                    summary_zh=summary_and_tags.summary_zh,
                    translated_body_zh=translation.translated_body_zh,
                    translation_status="succeeded",
                    summary_status="succeeded",
                    tagging_status="succeeded",
                    tags=summary_and_tags.tags,
                    content_type=translation.content_type,
                    classification_reason=translation.classification_reason,
                )
                finalize_article_enrichment_run(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    status="succeeded",
                )
    except Exception as exc:
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="failed",
            error_message=str(exc),
        )

    return get_article_enrichment_run(
        database_url=database_url,
        enrichment_run_id=enrichment_run.enrichment_run_id,
    )
```

- [ ] **Step 4.6: Verify article-processing-run handles `skipped_advertisement` as a success**

Open `src/newspaper_translator/document_processing.py` and confirm `process_article_processing_run` already only checks `enrichment_run.status == "succeeded"` (line ~1038). Update that check to also treat `skipped_advertisement` as a successful processing run:

```python
    if enrichment_run.status in ("succeeded", "skipped_advertisement"):
        return succeed_article_processing_run(
            database_url=database_url,
            article_key=article_key,
            last_success_input_hash=enrichment_run.input_hash,
        )
```

(Per the spec: "mark the article processing run as `succeeded` with `current_step = completed` and the current input hash".)

- [ ] **Step 4.7: Run the enrichment and document-processing tests**

```bash
./.venv/bin/python -m unittest tests.test_article_enrichment tests.test_document_processing 2>&1 | tail -10
```

Expected: `OK`.

- [ ] **Step 4.8: Commit**

```bash
git add src/newspaper_translator/article_enrichment.py src/newspaper_translator/document_processing.py tests/test_article_enrichment.py
git commit -m "Branch enrichment on content_type and skip ads through translator"
```

---

## Task 5: Worker config — new env vars and defaults

**Files:**
- Modify: `src/newspaper_translator/worker.py:108-185` (the env-driven builders) and `src/newspaper_translator/worker.py:315-381` (`run_worker_loop`)
- Test: `tests/test_worker.py`

- [ ] **Step 5.1: Write the failing test for default article concurrency = 4**

Add the following test to `tests/test_worker.py` (use a class that already covers env-driven builders; otherwise add a new `WorkerThroughputDefaultsTests(unittest.TestCase)` class):

```python
class WorkerThroughputDefaultsTests(unittest.TestCase):
    def test_default_article_worker_concurrency_is_four(self) -> None:
        from newspaper_translator.worker import _read_int_setting

        env: dict[str, str] = {}
        article_concurrency = _read_int_setting(
            env,
            "ARTICLE_WORKER_CONCURRENCY",
            default=4,
        )
        document_concurrency = _read_int_setting(
            env,
            "DOCUMENT_WORKER_CONCURRENCY",
            default=2,
        )

        self.assertEqual(article_concurrency, 4)
        self.assertEqual(document_concurrency, 2)

    def test_default_article_worker_batch_size_is_eight(self) -> None:
        from newspaper_translator.worker import _read_int_setting

        env: dict[str, str] = {}
        batch_size = _read_int_setting(
            env,
            "ARTICLE_WORKER_BATCH_SIZE",
            default=8,
        )
        self.assertEqual(batch_size, 8)
```

- [ ] **Step 5.2: Run the tests to verify they pass for the helper defaults**

```bash
./.venv/bin/python -m unittest tests.test_worker -v 2>&1 | tail -10
```

Expected: PASS — these defaults are caller-supplied. They guard against accidentally regressing the default values in the real call sites.

- [ ] **Step 5.3: Update `build_run_processing_tick_from_env` and `build_run_scheduler_tick_from_env` to use new defaults**

In `src/newspaper_translator/worker.py`, change every site that resolves `ARTICLE_WORKER_CONCURRENCY` to default to `4` (not `document_limit`). For example, in `build_run_scheduler_tick_from_env` (line ~115) and `build_run_processing_tick_from_env` (line ~166):

```python
    article_limit = _read_int_setting(
        env,
        "ARTICLE_WORKER_CONCURRENCY",
        default=4,
    )
```

Both functions also need a new `article_batch_size`:

```python
    article_batch_size = _read_int_setting(
        env,
        "ARTICLE_WORKER_BATCH_SIZE",
        default=8,
    )
```

Pass `article_batch_size` through to `run_processing_tick(...)` (and through `run_scheduler_tick(...)` to the inner `run_processing_tick(...)`) — Task 6 adds the matching parameter to those functions.

- [ ] **Step 5.4: Add the failing test for active vs idle poll cadence**

Add the following test to the same throughput-defaults class. It uses `run_worker_loop`'s injection seams.

```python
    def test_active_interval_is_used_when_processing_did_work(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []

        def fake_sleep(seconds: int) -> None:
            sleep_calls.append(seconds)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///:memory:",
            "STORAGE_ROOT": "/tmp",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS": "10",
            "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        def stub_processing_tick():
            return SimpleNamespace(did_work=True, scheduler_run_id="run-1")

        def stub_run_startup_maintenance(**_kwargs):
            return {}

        def stub_get_last_started_at(*, database_url: str) -> str | None:
            return "2026-05-06T12:00:00"

        def stub_should_run_catch_up_tick(**_kwargs) -> bool:
            return False

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-06T12:00:00",
            sleep_fn=fake_sleep,
            max_loops=1,
            run_startup_maintenance_fn=stub_run_startup_maintenance,
            get_last_scheduler_run_started_at_fn=stub_get_last_started_at,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(sleep_calls, [10])

    def test_idle_interval_is_used_when_processing_finds_no_work(self) -> None:
        from newspaper_translator.worker import run_worker_loop

        sleep_calls: list[int] = []

        def fake_sleep(seconds: int) -> None:
            sleep_calls.append(seconds)

        env = {
            "APP_ENV": "test",
            "DATABASE_URL": "sqlite:///:memory:",
            "STORAGE_ROOT": "/tmp",
            "GMAIL_CONFIG_PATH": "/tmp/gmail-config.json",
            "PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS": "10",
            "PROCESSING_IDLE_POLL_INTERVAL_SECONDS": "60",
        }

        def stub_processing_tick():
            return SimpleNamespace(did_work=False, scheduler_run_id=None)

        def stub_run_startup_maintenance(**_kwargs):
            return {}

        def stub_get_last_started_at(*, database_url: str) -> str | None:
            return "2026-05-06T12:00:00"

        run_worker_loop(
            env=env,
            now_fn=lambda: "2026-05-06T12:00:00",
            sleep_fn=fake_sleep,
            max_loops=1,
            run_startup_maintenance_fn=stub_run_startup_maintenance,
            get_last_scheduler_run_started_at_fn=stub_get_last_started_at,
            recover_stale_document_runs_fn=lambda: [],
            recover_stale_article_runs_fn=lambda: [],
            run_import_tick_fn=lambda *, trigger_type: "import-1",
            run_processing_tick_fn=stub_processing_tick,
        )

        self.assertEqual(sleep_calls, [60])
```

- [ ] **Step 5.5: Run the tests to verify they fail**

```bash
./.venv/bin/python -m unittest tests.test_worker.WorkerThroughputDefaultsTests -v 2>&1 | tail -25
```

Expected: FAIL — `run_worker_loop` currently uses a single `processing_poll_interval_seconds` and ignores the return value of the processing tick.

- [ ] **Step 5.6: Update `run_worker_loop` to use active/idle intervals based on tick result**

Replace the body of `run_worker_loop` (line ~315) with:

```python
def run_worker_loop(
    *,
    env: dict[str, str],
    now_fn=None,
    sleep_fn=None,
    max_loops: int | None = None,
    run_startup_maintenance_fn=run_startup_maintenance,
    get_last_scheduler_run_started_at_fn=get_last_import_run_started_at,
    recover_stale_document_runs_fn=None,
    recover_stale_article_runs_fn=None,
    run_scheduler_tick_fn=None,
    run_import_tick_fn=None,
    run_processing_tick_fn=None,
) -> None:
    app_settings = AppSettings.from_env(env)
    now = now_fn or _current_timestamp
    sleep = sleep_fn or time.sleep
    import_interval_seconds = _read_int_setting(
        env,
        "GMAIL_IMPORT_INTERVAL_SECONDS",
        default=_read_int_setting(env, "SCHEDULER_INTERVAL_SECONDS", default=7200),
    )
    active_poll_interval_seconds = _read_int_setting(
        env,
        "PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS",
        default=10,
    )
    idle_poll_interval_seconds = _read_int_setting(
        env,
        "PROCESSING_IDLE_POLL_INTERVAL_SECONDS",
        default=60,
    )
    recover = recover_stale_document_runs_fn or build_recover_stale_document_runs_from_env(env)
    recover_articles = recover_stale_article_runs_fn or build_recover_stale_article_runs_from_env(env)
    run_import_tick = (
        run_import_tick_fn
        or run_scheduler_tick_fn
        or build_run_import_tick_from_env(env)
    )
    run_processing_tick_callback = run_processing_tick_fn or build_run_processing_tick_from_env(env)

    run_startup_maintenance_fn(
        last_scheduler_run_started_at=get_last_scheduler_run_started_at_fn(
            database_url=app_settings.database_url,
        ),
        now=now(),
        interval_seconds=import_interval_seconds,
        recover_stale_document_runs=recover,
        recover_stale_article_runs=recover_articles,
        run_scheduler_tick=run_import_tick,
    )

    loop_count = 0
    processing_running = False
    last_did_work = False
    while max_loops is None or loop_count < max_loops:
        sleep(active_poll_interval_seconds if last_did_work else idle_poll_interval_seconds)
        if should_run_catch_up_tick(
            last_scheduler_run_started_at=get_last_scheduler_run_started_at_fn(
                database_url=app_settings.database_url,
            ),
            now=now(),
            interval_seconds=import_interval_seconds,
        ):
            run_import_tick(trigger_type="interval")

        if not processing_running:
            processing_running = True
            try:
                tick_result = run_processing_tick_callback()
            finally:
                processing_running = False
            last_did_work = bool(getattr(tick_result, "did_work", False))
        loop_count += 1
```

The tick callback now needs to return an object with a `did_work` attribute. Task 6 wires this up in `run_processing_tick(...)`.

- [ ] **Step 5.7: Run the worker tests**

```bash
./.venv/bin/python -m unittest tests.test_worker -v 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 5.8: Commit**

```bash
git add src/newspaper_translator/worker.py tests/test_worker.py
git commit -m "Add active/idle poll intervals and raise article concurrency default"
```

---

## Task 6: Article tick — batch size > concurrency, idle no-op

**Files:**
- Modify: `src/newspaper_translator/document_processing.py:1531-1650` (`run_processing_tick`); add a new helper for the lightweight queue check
- Test: `tests/test_document_processing.py`

- [ ] **Step 6.1: Failing test — article batch size can exceed concurrency**

Add the following test method inside the same `TestCase` that contains `test_processing_tick_processes_documents_before_articles` in `tests/test_document_processing.py`:

```python
    def test_article_tick_runs_batch_size_with_bounded_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                "message-1:attachment-1:hash-1",
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
            self._persist_parsed_document_articles(
                database_url=database_url,
                document_key=document_key,
                article_count=8,
            )
            for article in list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            ):
                create_article_processing_run(
                    database_url=database_url,
                    article_id=article.article_id,
                )

            in_flight: list[int] = []
            in_flight_lock = threading.Lock()
            peak_in_flight = 0
            processed: list[str] = []

            def process_one_document(*, document_key, scheduler_run_id, locked_by):
                return SimpleNamespace(status="succeeded")

            def process_one_article(*, article_key, locked_by):
                nonlocal peak_in_flight
                with in_flight_lock:
                    in_flight.append(article_key)
                    peak_in_flight = max(peak_in_flight, len(in_flight))
                try:
                    time.sleep(0.05)
                    return succeed_article_processing_run(
                        database_url=database_url,
                        article_key=article_key,
                        last_success_input_hash="hash-x",
                    )
                finally:
                    with in_flight_lock:
                        in_flight.remove(article_key)
                        processed.append(article_key)

            scheduler_run = run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=process_one_document,
                document_limit=2,
                process_one_article=process_one_article,
                article_limit=4,
                article_batch_size=8,
            )

        self.assertEqual(len(processed), 8)
        self.assertLessEqual(peak_in_flight, 4)
        self.assertEqual(scheduler_run.selected_document_count, 1 + 8)
        self.assertTrue(scheduler_run.did_work)
```

If `_persist_parsed_document_articles` does not currently accept an `article_count` argument, extend it (or copy and adjust the helper to insert the requested number of articles). Add `import time` and `import threading` to the test module if they are not yet present.

- [ ] **Step 6.2: Failing test — empty queue does not create a scheduler run**

Add this test method:

```python
    def test_processing_tick_skips_scheduler_run_when_no_eligible_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            scheduler_run = run_processing_tick(
                database_url=database_url,
                trigger_type="processing",
                process_one_document=lambda **_kw: SimpleNamespace(status="succeeded"),
                document_limit=4,
                process_one_article=lambda **_kw: SimpleNamespace(status="succeeded"),
                article_limit=4,
                article_batch_size=8,
            )

            connection = sqlite3.connect(database_path)
            try:
                scheduler_run_count = connection.execute(
                    "SELECT COUNT(*) FROM scheduler_runs"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertFalse(scheduler_run.did_work)
        self.assertEqual(scheduler_run.scheduler_run_id, None)
        self.assertEqual(scheduler_run_count, 0)
```

- [ ] **Step 6.3: Run the tests to verify they fail**

```bash
./.venv/bin/python -m unittest tests.test_document_processing -v 2>&1 | tail -25
```

Expected: FAIL — `run_processing_tick` does not accept `article_batch_size`, does not return `did_work`, and always creates a scheduler run.

- [ ] **Step 6.4: Update `run_processing_tick` to support batch size, idle short-circuit, and `did_work`**

In `src/newspaper_translator/document_processing.py`, change the signature and body of `run_processing_tick` (line ~1531):

```python
def run_processing_tick(
    *,
    database_url: str,
    trigger_type: str,
    process_one_document,
    document_limit: int,
    process_one_article=None,
    article_limit: int = 0,
    article_batch_size: int | None = None,
    import_run_id: str | None = None,
    locked_by_prefix: str = "scheduler-worker",
    article_locked_by_prefix: str = "article-worker",
    log_event=None,
) -> "ProcessingTickResult":
    if article_batch_size is None:
        article_batch_size = article_limit

    eligible_runs = list_eligible_document_processing_runs(
        database_url=database_url,
        limit=document_limit,
    )
    eligible_article_runs = (
        list_eligible_article_processing_runs(
            database_url=database_url,
            limit=article_batch_size,
        )
        if process_one_article is not None and article_batch_size > 0
        else []
    )

    if not eligible_runs and not eligible_article_runs:
        _log_event(
            log_event,
            event="scheduler.processing.idle",
            details={"trigger_type": trigger_type},
        )
        return ProcessingTickResult(
            scheduler_run_id=None,
            did_work=False,
            selected_document_count=0,
            completed_document_count=0,
            failed_document_count=0,
        )

    scheduler_run = create_scheduler_run(
        database_url=database_url,
        trigger_type=trigger_type,
    )
    _log_event(
        log_event,
        event="scheduler.processing.started",
        details={
            "scheduler_run_id": scheduler_run.scheduler_run_id,
            "trigger_type": trigger_type,
        },
    )

    completed_document_count = 0
    failed_document_count = 0
    error_messages: list[str] = []
    if eligible_runs:
        max_workers = max(1, len(eligible_runs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_document_key = {
                executor.submit(
                    process_one_document,
                    document_key=eligible_run.document_key,
                    scheduler_run_id=scheduler_run.scheduler_run_id,
                    locked_by=f"{locked_by_prefix}-{index}",
                ): eligible_run.document_key
                for index, eligible_run in enumerate(eligible_runs, start=1)
            }
            for future in as_completed(future_to_document_key):
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_document_count += 1
                    error_messages.append(str(exc))
                    continue

                if getattr(result, "status", "") == "succeeded":
                    completed_document_count += 1
                else:
                    failed_document_count += 1

    if eligible_article_runs:
        max_article_workers = max(1, min(article_limit, len(eligible_article_runs)))
        with ThreadPoolExecutor(max_workers=max_article_workers) as executor:
            future_to_article_key = {
                executor.submit(
                    process_one_article,
                    article_key=eligible_run.article_key,
                    locked_by=f"{article_locked_by_prefix}-{index}",
                ): eligible_run.article_key
                for index, eligible_run in enumerate(eligible_article_runs, start=1)
            }
            for future in as_completed(future_to_article_key):
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_document_count += 1
                    error_messages.append(str(exc))
                    continue

                if getattr(result, "status", "") == "succeeded":
                    completed_document_count += 1
                else:
                    failed_document_count += 1

    final_status = "succeeded"
    if failed_document_count and completed_document_count:
        final_status = "partial"
    elif failed_document_count:
        final_status = "failed"

    selected_document_count = len(eligible_runs) + len(eligible_article_runs)
    finalize_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
        status=final_status,
        import_run_id=import_run_id,
        selected_document_count=selected_document_count,
        completed_document_count=completed_document_count,
        failed_document_count=failed_document_count,
        error_message="; ".join(error_messages) if error_messages else None,
    )
    finalized_run = get_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
    )
    _log_event(
        log_event,
        event="scheduler.processing.finished",
        details={
            "scheduler_run_id": finalized_run.scheduler_run_id,
            "status": finalized_run.status,
            "selected_document_count": finalized_run.selected_document_count,
            "completed_document_count": finalized_run.completed_document_count,
            "failed_document_count": finalized_run.failed_document_count,
        },
    )
    return ProcessingTickResult(
        scheduler_run_id=finalized_run.scheduler_run_id,
        did_work=True,
        selected_document_count=finalized_run.selected_document_count,
        completed_document_count=finalized_run.completed_document_count,
        failed_document_count=finalized_run.failed_document_count,
    )
```

Add the new dataclass near the top of the same file, alongside `SchedulerRun`:

```python
@dataclass(frozen=True)
class ProcessingTickResult:
    scheduler_run_id: str | None
    did_work: bool
    selected_document_count: int
    completed_document_count: int
    failed_document_count: int
```

The article tick now uses `min(article_limit, len(eligible_article_runs))` as `max_workers`, so the thread pool is bounded by `ARTICLE_WORKER_CONCURRENCY` regardless of how many items the batch claimed.

- [ ] **Step 6.5: Update `run_scheduler_tick` to return the new result type**

`run_scheduler_tick` (line ~1468) currently returns `SchedulerRun`. Update its return type to `ProcessingTickResult` and pass `article_batch_size` through:

```python
def run_scheduler_tick(
    *,
    database_url: str,
    trigger_type: str,
    import_documents,
    process_one_document,
    document_limit: int,
    process_one_article=None,
    article_limit: int = 0,
    article_batch_size: int | None = None,
    locked_by_prefix: str = "scheduler-worker",
    article_locked_by_prefix: str = "article-worker",
    log_event=None,
) -> "ProcessingTickResult":
    _log_event(
        log_event,
        event="scheduler.tick.started",
        details={"trigger_type": trigger_type},
    )
    _log_event(
        log_event,
        event="scheduler.import.started",
        details={"trigger_type": trigger_type},
    )
    import_result = import_documents()
    import_run_id = getattr(import_result, "run_id", None)
    _log_event(
        log_event,
        event="scheduler.import.finished",
        details={
            "trigger_type": trigger_type,
            "import_run_id": import_run_id,
        },
    )
    finalized_run = run_processing_tick(
        database_url=database_url,
        trigger_type=trigger_type,
        process_one_document=process_one_document,
        document_limit=document_limit,
        process_one_article=process_one_article,
        article_limit=article_limit,
        article_batch_size=article_batch_size,
        import_run_id=import_run_id,
        locked_by_prefix=locked_by_prefix,
        article_locked_by_prefix=article_locked_by_prefix,
        log_event=log_event,
    )
    _log_event(
        log_event,
        event="scheduler.tick.finished",
        details={
            "scheduler_run_id": finalized_run.scheduler_run_id,
            "did_work": finalized_run.did_work,
            "selected_document_count": finalized_run.selected_document_count,
            "completed_document_count": finalized_run.completed_document_count,
            "failed_document_count": finalized_run.failed_document_count,
        },
    )
    return finalized_run
```

- [ ] **Step 6.6: Wire `article_batch_size` through the worker builders**

In `src/newspaper_translator/worker.py`, update both `build_run_processing_tick_from_env` and `build_run_scheduler_tick_from_env` so they pass `article_batch_size=article_batch_size` to the inner functions. For example, inside `build_run_processing_tick_from_env`:

```python
    def run_tick():
        return run_processing_tick(
            database_url=app_settings.database_url,
            trigger_type="processing",
            process_one_document=process_one_document,
            document_limit=document_limit,
            process_one_article=process_one_article,
            article_limit=article_limit,
            article_batch_size=article_batch_size,
        )

    return run_tick
```

The previous return value (`scheduler_run.scheduler_run_id`) is no longer the right shape; the worker loop only needs the `did_work` attribute, so return `tick_result` directly. Similarly update `build_run_scheduler_tick_from_env` to return the `ProcessingTickResult`.

The existing tests at `tests/test_worker.py` that call these builders may need to stop indexing the return value as a string ID; if they fail in Step 6.7 update them to read `.scheduler_run_id` from the returned object.

- [ ] **Step 6.7: Run the tests**

```bash
./.venv/bin/python -m unittest tests.test_document_processing tests.test_worker -v 2>&1 | tail -30
```

Expected: PASS for the two new tests and all existing ones. If a pre-existing test fails because it asserted `selected_document_count` from the returned `SchedulerRun`, update it to read from `ProcessingTickResult` (the field names are identical).

- [ ] **Step 6.8: Commit**

```bash
git add src/newspaper_translator/document_processing.py src/newspaper_translator/worker.py tests/test_document_processing.py tests/test_worker.py
git commit -m "Make article tick bounded-concurrency batched and idle-skip scheduler runs"
```

---

## Task 7: Pass new env vars through Compose and `.env.example`

**Files:**
- Modify: `docker-compose.yml:67-114` (`worker` service `environment:` block)
- Modify: `.env.example`
- Test: existing `tests/test_container_scaffolding.py` (extend to cover new keys if it currently checks Compose contents)

- [ ] **Step 7.1: If `tests/test_container_scaffolding.py` currently asserts on Compose env keys, add failing assertions for the new keys**

Run:

```bash
grep -n "ARTICLE_WORKER_CONCURRENCY\|DOCUMENT_WORKER_CONCURRENCY\|PROCESSING_POLL_INTERVAL_SECONDS" tests/test_container_scaffolding.py
```

If matches exist, add assertions in the same test for:

```python
self.assertIn("ARTICLE_WORKER_CONCURRENCY", compose_text)
self.assertIn("ARTICLE_WORKER_BATCH_SIZE", compose_text)
self.assertIn("PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS", compose_text)
self.assertIn("PROCESSING_IDLE_POLL_INTERVAL_SECONDS", compose_text)
```

If no such test exists, skip directly to Step 7.2 — the wiring is exercised through `tests/test_worker.py` defaults.

- [ ] **Step 7.2: Update `docker-compose.yml`**

Inside the `worker.environment:` block in `docker-compose.yml` (around line 77), add these entries (sorted near the existing `*_INTERVAL_SECONDS` settings):

```yaml
      ARTICLE_WORKER_CONCURRENCY: ${ARTICLE_WORKER_CONCURRENCY:-4}
      DOCUMENT_WORKER_CONCURRENCY: ${DOCUMENT_WORKER_CONCURRENCY:-2}
      ARTICLE_WORKER_BATCH_SIZE: ${ARTICLE_WORKER_BATCH_SIZE:-8}
      PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS: ${PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS:-10}
      PROCESSING_IDLE_POLL_INTERVAL_SECONDS: ${PROCESSING_IDLE_POLL_INTERVAL_SECONDS:-60}
```

- [ ] **Step 7.3: Update `.env.example`**

Append the following lines to `.env.example` (preserve the file's existing trailing-newline convention):

```bash
# Worker throughput
ARTICLE_WORKER_CONCURRENCY=4
DOCUMENT_WORKER_CONCURRENCY=2
ARTICLE_WORKER_BATCH_SIZE=8
PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS=10
PROCESSING_IDLE_POLL_INTERVAL_SECONDS=60
```

- [ ] **Step 7.4: Sanity-check Compose still parses**

```bash
docker compose -f docker-compose.yml config >/dev/null
```

Expected: exit code `0`.

- [ ] **Step 7.5: Run the test suite**

```bash
./.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
```

Expected: `OK`.

- [ ] **Step 7.6: Commit**

```bash
git add docker-compose.yml .env.example tests/test_container_scaffolding.py
git commit -m "Pass article worker concurrency and poll settings through Compose"
```

---

## Task 8: Reader-facing API filtering

**Files:**
- Modify: `src/newspaper_translator/api/queries.py:147-249` (`get_overview_view`, `get_filter_options_view`), `src/newspaper_translator/api/queries.py:341-426` (`get_document_processing_detail_view`), `src/newspaper_translator/api/queries.py:569-691` (`list_article_card_views`, `list_focus_tag_article_card_views`)
- Test: `tests/test_api_queries.py`

The principle: a "skipped advertisement" article is one whose **latest non-failed** enrichment run has `status = 'skipped_advertisement'`. We add a SQL fragment to exclude such articles from reader joins.

- [ ] **Step 8.1: Add the failing test for `list_article_card_views` excluding ads**

Add the following to `tests/test_api_queries.py` (use the closest existing reader test as a template; insert into the appropriate `TestCase`). The helper `_seed_article_with_enrichment` should mirror existing helpers in that file.

```python
    def test_list_article_card_views_excludes_skipped_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            article_visible = self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Visible Article",
                content_type="article",
                run_status="succeeded",
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            cards = list_article_card_views(database_url=database_url)

        titles = [card.title_en for card in cards]
        self.assertIn("Visible Article", titles)
        self.assertNotIn("Hidden Advertisement", titles)
        self.assertEqual(cards[0].article_id, article_visible.article_id)
```

If no `_seed_article_with_enrichment` helper exists in this test file, add the following helper to the test class. It must accept `database_url`, `title_en`, `content_type`, `run_status`, optional `classification_reason="auto."`, optional `tags=None`, and optional `document_key=None` so it can seed multiple articles under the same document.

```python
    def _seed_article_with_enrichment(
        self,
        *,
        database_url: str,
        title_en: str,
        content_type: str,
        run_status: str,
        classification_reason: str = "auto.",
        tags: list[str] | None = None,
        document_key: str | None = None,
    ) -> "StoredFinalArticle":
        if document_key is None:
            document_key = f"message-{uuid.uuid4()}:attachment-1:hash-1"
            self._insert_document(
                pathlib.Path(database_url.replace("sqlite:///", "")),
                document_key,
            )
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date="2026-04-20",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=self._build_parse_result(title=title_en, body_suffix="body."),
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )
        article = list_parse_run_final_articles(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
        )[0]

        enrichment = create_article_enrichment_run(
            database_url=database_url,
            article_id=article.article_id,
            parse_run_id=parse_run.parse_run_id,
            provider_name="gemini",
            model_name="gemini-2.5-flash",
            prompt_version="article-enrichment-v3",
            input_hash=f"hash-{article.article_id}",
        )
        if content_type == "advertisement":
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment.enrichment_run_id,
                translated_title_zh=None,
                summary_zh=None,
                translated_body_zh=None,
                translation_status="skipped",
                summary_status="skipped",
                tagging_status="skipped",
                tags=[],
                content_type=content_type,
                classification_reason=classification_reason,
            )
        else:
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment.enrichment_run_id,
                translated_title_zh="标题",
                summary_zh="摘要。",
                translated_body_zh="正文。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=tags or ["标签一", "标签二", "标签三"],
                content_type=content_type,
                classification_reason=classification_reason,
            )
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment.enrichment_run_id,
            status=run_status,
        )
        return article
```

(Reuse the existing `_insert_document` and `_build_parse_result` helpers from elsewhere in `tests/test_api_queries.py` — if they don't exist, copy them from `tests/test_article_enrichment.py`.)

Add the corresponding tests for the other reader surfaces:

```python
    def test_get_overview_article_count_excludes_skipped_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Visible Article",
                content_type="article",
                run_status="succeeded",
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            overview = get_overview_view(database_url=database_url)

        self.assertEqual(overview.article_count, 1)

    def test_get_filter_options_excludes_advertisement_only_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Normal",
                content_type="article",
                run_status="succeeded",
                tags=["T1", "T2", "T3"],
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Ad",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            filters = get_filter_options_view(database_url=database_url)

        self.assertIn("T1", filters.tags)

    def test_get_document_processing_detail_visible_articles_excludes_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            shared_document_key = f"message-shared:attachment-1:hash-1"
            self._insert_document(database_path, shared_document_key)
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Normal Article",
                content_type="article",
                run_status="succeeded",
                document_key=shared_document_key,
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Ad",
                content_type="advertisement",
                run_status="skipped_advertisement",
                document_key=shared_document_key,
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=shared_document_key,
            )

            view = get_document_processing_detail_view(
                database_url=database_url,
                document_key=shared_document_key,
            )

        titles = [article.title_en for article in view.visible_articles]
        self.assertIn("Normal Article", titles)
        self.assertNotIn("Hidden Ad", titles)
        self.assertEqual(view.visible_article_count, 1)
```

(Note: the document-detail test creates two parse runs against the same `document_key`, so `list_latest_document_articles` returns articles from the most recent parse run. If the helper above seeds the ad first and the article second, the ad's parse run will be older and both articles won't co-occur in `visible_articles`. To force both into the latest parse run, refactor `_seed_article_with_enrichment` to optionally accept an existing `parse_run_id` and reuse it for the second call. Keep that refactor self-contained; do not let it leak into the simpler tests above.)

- [ ] **Step 8.2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m unittest tests.test_api_queries -v 2>&1 | tail -25
```

Expected: FAIL — the reader views still surface advertisement articles.

- [ ] **Step 8.3: Add a SQL helper for "latest usable enrichment status per article"**

In `src/newspaper_translator/api/queries.py`, near the top of the module (after the imports but before the dataclasses), add:

```python
_LATEST_USABLE_ENRICHMENT_SUBQUERY = """
SELECT r.article_id, r.status
FROM article_enrichment_runs r
WHERE r.status IN ('succeeded', 'partial', 'skipped_advertisement')
  AND r.finished_at = (
        SELECT MAX(r2.finished_at)
        FROM article_enrichment_runs r2
        WHERE r2.article_id = r.article_id
          AND r2.status IN ('succeeded', 'partial', 'skipped_advertisement')
  )
"""

_NOT_SKIPPED_ADVERTISEMENT_CLAUSE = """
NOT EXISTS (
    SELECT 1
    FROM ({latest}) latest
    WHERE latest.article_id = a.article_id
      AND latest.status = 'skipped_advertisement'
)
""".format(latest=_LATEST_USABLE_ENRICHMENT_SUBQUERY)
```

- [ ] **Step 8.4: Update `list_article_card_views`**

In the function body (line ~569), insert the new clause inside the existing `WHERE ... AND ...` chain, after the existing `parse_runs.status = 'succeeded'` filter:

```python
        query = """
        SELECT
            a.article_id,
            a.document_key,
            d.source_name,
            a.publication_date,
            a.title_en
        FROM final_articles a
        JOIN documents d
            ON d.document_key = a.document_key
        JOIN parse_runs p
            ON p.parse_run_id = a.parse_run_id
        WHERE p.status = 'succeeded'
          AND p.parse_run_id = (
                SELECT p2.parse_run_id
                FROM parse_runs p2
                WHERE p2.document_key = a.document_key
                  AND p2.status = 'succeeded'
                ORDER BY p2.finished_at DESC, p2.rowid DESC
                LIMIT 1
          )
          AND """ + _NOT_SKIPPED_ADVERTISEMENT_CLAUSE
```

(The remaining `if source:` / `if tag:` clauses already use `query += " AND ..."`; they continue to compose correctly.)

- [ ] **Step 8.5: Update `get_overview_view.article_count`**

In `get_overview_view` (line ~157), change the `article_count` query to add the same `NOT EXISTS` clause:

```python
        article_count = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM final_articles a
            WHERE a.parse_run_id IN (
                SELECT p.parse_run_id
                FROM parse_runs p
                WHERE p.status = 'succeeded'
                  AND DATE(p.finished_at) = DATE('now')
            )
              AND {_NOT_SKIPPED_ADVERTISEMENT_CLAUSE}
            """
        ).fetchone()[0]
```

Apply the same change to `pending_article_count` so pending counts also exclude advertisements.

- [ ] **Step 8.6: Update `get_filter_options_view`**

Tag-source joins should not surface tags from advertisement-only articles. Update the tag query:

```python
        tag_rows = connection.execute(
            f"""
            SELECT DISTINCT t.tag_text
            FROM article_tags t
            JOIN article_enrichment_runs r
                ON r.enrichment_run_id = t.enrichment_run_id
            JOIN final_articles a
                ON a.article_id = r.article_id
            WHERE r.status IN ('partial', 'succeeded')
              AND {_NOT_SKIPPED_ADVERTISEMENT_CLAUSE}
            ORDER BY t.tag_text ASC
            """
        ).fetchall()
```

(Sources do not need filtering — a source is visible whenever any non-ad article exists. Sources without any non-ad article will already drop out via `parse_runs.status = 'succeeded'` joining; if that turns out to surface ad-only sources during testing, add `EXISTS (SELECT 1 FROM final_articles a ...)` then.)

- [ ] **Step 8.7: Update `get_document_processing_detail_view` to drop ad articles from `visible_articles`**

In `get_document_processing_detail_view` (line ~341), wrap the visible-article construction with a content-type check:

```python
    visible_articles: list[DocumentVisibleArticleView] = []
    for article in list_latest_document_articles(
        database_url=database_url,
        document_key=document_key,
    ):
        try:
            enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )
        except LookupError:
            enrichment = None

        if enrichment is not None and enrichment.status == "skipped_advertisement":
            continue

        title_zh = None
        summary_zh = None
        reading_status = "english_fallback"
        if enrichment is not None:
            title_zh = enrichment.translated_title_zh
            summary_zh = enrichment.summary_zh
            reading_status = "ready"

        visible_articles.append(
            DocumentVisibleArticleView(
                article_id=article.article_id,
                publication_date=article.publication_date,
                title_en=article.title_en,
                title_zh=title_zh,
                summary_zh=summary_zh,
                reading_status=reading_status,
            )
        )
```

- [ ] **Step 8.8: Update `list_focus_tag_article_card_views`**

This function already delegates to `list_article_card_views`, so the exclusion propagates automatically once Step 8.4 is applied. Verify there is no second SQL surface inside the focus-tag function that bypasses the filter — there should not be.

- [ ] **Step 8.9: Run the tests**

```bash
./.venv/bin/python -m unittest tests.test_api_queries 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 8.10: Commit**

```bash
git add src/newspaper_translator/api/queries.py tests/test_api_queries.py
git commit -m "Exclude skipped advertisements from reader-facing API surfaces"
```

---

## Task 9: Operator visibility for content_type & classification_reason

**Files:**
- Modify: `src/newspaper_translator/api/queries.py:106-128` (`ArticleProcessingDetailView`), `src/newspaper_translator/api/queries.py:429-485` (`get_article_processing_detail_view`)
- Test: `tests/test_api_queries.py`

- [ ] **Step 9.1: Failing test — operator detail view exposes classification fields**

Add to `tests/test_api_queries.py`:

```python
    def test_article_processing_detail_view_exposes_advertisement_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            article = self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
                classification_reason="Display ad block.",
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )
            article_key = get_final_article(
                database_url=database_url,
                article_id=article.article_id,
            ).article_key

            view = get_article_processing_detail_view(
                database_url=database_url,
                article_key=article_key,
            )

        self.assertEqual(view.content_type, "advertisement")
        self.assertEqual(view.classification_reason, "Display ad block.")
        self.assertEqual(view.latest_enrichment_status, "skipped_advertisement")
```

The helper `_seed_article_with_enrichment` from Task 8 must accept a `classification_reason` keyword (already required in `record_article_enrichment_outputs`).

- [ ] **Step 9.2: Run the test to verify it fails**

```bash
./.venv/bin/python -m unittest tests.test_api_queries.ArticleProcessingDetailViewTests -v 2>&1 | tail -15
```

(Substitute the actual test class name if different.) Expected: FAIL — `ArticleProcessingDetailView` has no `content_type`, `classification_reason`, or `latest_enrichment_status` field yet.

- [ ] **Step 9.3: Update the dataclass**

In `src/newspaper_translator/api/queries.py`, replace `ArticleProcessingDetailView` (line 106):

```python
@dataclass(frozen=True)
class ArticleProcessingDetailView:
    article_processing_run_id: str
    article_key: str
    article_id: str
    document_key: str
    source_name: str
    original_filename: str
    publication_date: str
    title_en: str
    source_page_numbers: list[int]
    status: str
    current_step: str
    automatic_failure_count: int
    last_error_message: str | None
    last_success_input_hash: str | None
    last_attempt_started_at: str | None
    last_attempt_finished_at: str | None
    locked_by: str | None
    lock_expires_at: str | None
    created_at: str
    updated_at: str
    latest_error_summary: str
    content_type: str
    classification_reason: str
    latest_enrichment_status: str | None
```

- [ ] **Step 9.4: Update `get_article_processing_detail_view`**

Replace the function body (line ~429) to also resolve the latest enrichment fields:

```python
def get_article_processing_detail_view(
    *,
    database_url: str,
    article_key: str,
) -> ArticleProcessingDetailView:
    run = get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )
    article = get_final_article(
        database_url=database_url,
        article_id=run.article_id,
    )
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        document_row = connection.execute(
            """
            SELECT source_name, original_filename
            FROM documents
            WHERE document_key = ?
            """,
            (article.document_key,),
        ).fetchone()
    finally:
        connection.close()

    if document_row is None:
        raise LookupError(f"Document not found for article processing: {article.document_key}")

    content_type = "article"
    classification_reason = ""
    latest_enrichment_status: str | None = None
    try:
        latest_enrichment = get_latest_article_enrichment(
            database_url=database_url,
            article_id=article.article_id,
        )
    except LookupError:
        latest_enrichment = None
    if latest_enrichment is not None:
        content_type = latest_enrichment.content_type
        classification_reason = latest_enrichment.classification_reason
        latest_enrichment_status = latest_enrichment.status

    latest_error_summary = "当前没有错误。"
    if run.last_error_message:
        latest_error_summary = f"{run.current_step}: {run.last_error_message}"

    return ArticleProcessingDetailView(
        article_processing_run_id=run.article_processing_run_id,
        article_key=run.article_key,
        article_id=run.article_id,
        document_key=article.document_key,
        source_name=document_row[0],
        original_filename=document_row[1],
        publication_date=article.publication_date,
        title_en=article.title_en,
        source_page_numbers=article.source_page_numbers,
        status=run.status,
        current_step=run.current_step,
        automatic_failure_count=run.automatic_failure_count,
        last_error_message=run.last_error_message,
        last_success_input_hash=run.last_success_input_hash,
        last_attempt_started_at=run.last_attempt_started_at,
        last_attempt_finished_at=run.last_attempt_finished_at,
        locked_by=run.locked_by,
        lock_expires_at=run.lock_expires_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        latest_error_summary=latest_error_summary,
        content_type=content_type,
        classification_reason=classification_reason,
        latest_enrichment_status=latest_enrichment_status,
    )
```

- [ ] **Step 9.5: Update `web.py` JSON serialization for the operator detail route**

```bash
grep -n "article_processing_run_id\|ArticleProcessingDetailView" src/newspaper_translator/web.py
```

If the route serializes the dataclass with `dataclasses.asdict`, no change is needed. Otherwise, add `content_type`, `classification_reason`, and `latest_enrichment_status` to the explicit serialization payload so the operator UI receives them.

- [ ] **Step 9.6: Run the tests**

```bash
./.venv/bin/python -m unittest tests.test_api_queries tests.test_web 2>&1 | tail -10
```

Expected: `OK`.

- [ ] **Step 9.7: Commit**

```bash
git add src/newspaper_translator/api/queries.py src/newspaper_translator/web.py tests/test_api_queries.py
git commit -m "Expose content_type and classification reason on operator detail view"
```

---

## Task 10: End-to-end smoke and regression

- [ ] **Step 10.1: Run the full unit test suite**

```bash
./.venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
```

Expected: `OK`.

- [ ] **Step 10.2: Manually verify the rollout defaults document the spec**

Confirm that with no extra environment variables set, the worker:

```bash
./.venv/bin/python -c "
from newspaper_translator.worker import _read_int_setting
env = {}
print('article_concurrency =', _read_int_setting(env, 'ARTICLE_WORKER_CONCURRENCY', default=4))
print('article_batch_size =', _read_int_setting(env, 'ARTICLE_WORKER_BATCH_SIZE', default=8))
print('active_interval =', _read_int_setting(env, 'PROCESSING_ACTIVE_POLL_INTERVAL_SECONDS', default=10))
print('idle_interval =', _read_int_setting(env, 'PROCESSING_IDLE_POLL_INTERVAL_SECONDS', default=60))
"
```

Expected output:

```
article_concurrency = 4
article_batch_size = 8
active_interval = 10
idle_interval = 60
```

- [ ] **Step 10.3: Verify Compose still parses cleanly**

```bash
docker compose -f docker-compose.yml config | grep -E "ARTICLE_WORKER|PROCESSING_(ACTIVE|IDLE)" | sort
```

Expected: prints the five new env entries with their default values.

- [ ] **Step 10.4: No commit**

This task is verification-only.

---

## Self-Review Notes

- Spec coverage:
  - Worker concurrency / batch size — Tasks 5, 6.
  - Active vs idle poll cadence — Tasks 5, 6.
  - Empty-queue tick skips `scheduler_runs` — Task 6 (Step 6.2 + Step 6.4 short-circuit).
  - Translator returns `content_type` + `classification_reason` — Task 3.
  - Conservative classification prompt — Task 3 prompt body.
  - Advertisement skip flow — Task 4.
  - Migration adds `content_type` and `classification_reason` — Task 1.
  - `skipped_advertisement` is a usable terminal status — Task 2 (`get_latest_article_enrichment` includes it) + Task 4 (`process_article_processing_run` succeeds on it).
  - Reader exclusion of advertisements — Task 8.
  - Operator visibility — Task 9.
  - Compose passes the settings — Task 7.
- Type consistency: `ProcessingTickResult` is the new return type of `run_processing_tick` and `run_scheduler_tick`; `ArticleTranslationResult` carries `content_type` everywhere; `LatestArticleEnrichment` has `content_type` and `classification_reason` consumed by both reader and operator views.
- Rollout safety: existing rows default to `content_type='article'` and `classification_reason=''`, and `get_latest_article_enrichment` falls back to `'article'` if `LEFT JOIN` produces NULLs, so dashboards keep working pre-backfill.
