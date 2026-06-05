# DeepSeek And Page-Sliced MinerU Design

Date: 2026-06-05

Related documents:

- [MinerU Phase 3 Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-mineru-phase-3-design.md)
- [Article Enrichment Execution Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-28-article-enrichment-execution-design.md)
- [Dual Worker Article Drain Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-07-dual-worker-article-drain-design.md)
- [Worker Error Mechanism Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-09-worker-error-mechanism-design.md)

External references:

- DeepSeek API Create Chat Completion: `https://api-docs.deepseek.com/api/create-chat-completion`
- DeepSeek JSON Output: `https://api-docs.deepseek.com/zh-cn/guides/json_mode`

## Overview

The project currently uses Gemini-flavored classes for three LLM responsibilities:

- explicit continuation matching for split newspaper fragments
- article translation and advertisement classification
- Chinese summary and tag generation

The project also currently submits each imported newspaper PDF to MinerU as one full document. This makes page number fidelity dependent on MinerU's whole-document Markdown output and forces the parser to infer article page membership after the fact.

This design changes both boundaries:

- DeepSeek becomes the primary LLM provider for continuation matching, translation, summary, and tags.
- MinerU parsing becomes page-sliced: split the source PDF into one-page PDFs, submit those page files to MinerU in batches of up to 30 files, then attach stable 1-based physical PDF page numbers to parsed fragments and final articles.

## Goals

- Use DeepSeek for all current LLM work, not only translation and summary.
- Read DeepSeek credentials and model selection from the existing `.env` keys:
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL`
  - `DEEPSEEK_MODEL`
- Preserve strict JSON contracts for continuation matching, translation/classification, and summary/tags.
- Replace full-document MinerU parsing with page-sliced parsing.
- Submit single-page PDFs to MinerU in batches of at most 30 files.
- Persist user-facing source page numbers as 1-based physical PDF page indexes.
- Preserve cross-page article behavior so a merged article from pages 1 and 7 records `[1, 7]`.
- Keep the current frontend and API page-number surfaces working with the improved source data.

## Non-Goals

- Removing all Gemini code in this slice.
- Supporting runtime provider switching in the UI.
- Adding non-explicit cross-page continuation inference.
- Parsing newspaper printed page labels such as `A1` or `A7` as authoritative source page numbers.
- Replacing MinerU with a local OCR or layout engine.
- Changing the article reader UX beyond using more accurate `source_page_numbers`.

## Product Decisions

DeepSeek fully replaces Gemini for active runtime behavior.

The implementation should keep existing Gemini classes temporarily for compatibility and smaller blast radius, but worker and CLI construction should use DeepSeek when building:

- continuation matcher
- article translator/classifier
- article summarizer/tagger

If DeepSeek configuration is missing or invalid, the runtime should fail fast with a configuration error. It should not silently fall back to Gemini in this slice.

Source page numbers are 1-based physical PDF page numbers. They are not newspaper section labels. This means the first PDF page is page `1`, even if the printed newspaper label is `A1`, `Page One`, blank, or unparseable.

MinerU page slicing uses batch uploads with up to 30 one-page PDF files per MinerU batch. The value `30` is the concurrency/batch width for this design and should be configurable only if implementation discovers a strong operational need.

## Existing System Touchpoints

### LLM Runtime

Current LLM code lives mostly in:

- `src/newspaper_translator/gemini.py`
- `src/newspaper_translator/config.py`
- `src/newspaper_translator/worker.py`
- `src/newspaper_translator/manage.py`

The existing Gemini OpenAI-compatible mode already sends `POST /chat/completions` requests with:

- `Authorization: Bearer ...`
- `model`
- `messages`
- `temperature: 0`
- `response_format: {"type": "json_object"}`

DeepSeek's API shape is compatible with this style. DeepSeek's JSON Output guide also requires that prompts explicitly instruct the model to output JSON, which the project's current prompts already do and should continue to do.

### MinerU Runtime

Current MinerU code lives mostly in:

- `src/newspaper_translator/mineru.py`
- `src/newspaper_translator/pdf.py`
- `src/newspaper_translator/article_pipeline.py`
- `src/newspaper_translator/article_store.py`

The current path is:

1. `persist_document_articles(...)` loads the raw PDF path from `documents`.
2. `mineru_client.parse_pdf(...)` submits the whole file to MinerU.
3. MinerU returns one `full.md`.
4. `build_parse_result_from_mineru_markdown(...)` extracts fragments and final articles.
5. `record_parse_run_result(...)` persists fragments, matches, final articles, and lineage.

The new path keeps the same high-level persistence ownership but changes the parse source from one whole-document Markdown file to an ordered list of page Markdown results.

## Recommended Architecture

### Provider-Neutral Chat JSON Layer

Add a small provider-neutral chat-completions JSON layer, either as a new module or as a narrowly extracted helper from the current Gemini implementation.

Recommended module name:

- `src/newspaper_translator/llm.py`

Recommended responsibilities:

- request transport protocol reuse
- chat-completions URL construction
- auth headers
- JSON request body construction
- response text extraction from `choices[0].message.content`
- status-code validation
- JSON parsing helpers shared by DeepSeek clients

This layer should not know newspaper-specific prompt semantics. It only knows how to send one prompt and return text or parsed JSON.

### DeepSeek Settings

Add a settings dataclass in `config.py`:

- `DeepSeekSettings`

Required environment:

- `DEEPSEEK_API_KEY`

Optional/defaulted environment:

- `DEEPSEEK_BASE_URL`, default `https://api.deepseek.com`
- `DEEPSEEK_MODEL`, default `deepseek-chat`
- `DEEPSEEK_TIMEOUT_SECONDS`, default to the current Gemini timeout default if not set

The project already has `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` in local `.env`. `.env.example` and `docker-compose.yml` should be updated so the container runtime receives the same keys.

### DeepSeek Newspaper Clients

Add newspaper-specific DeepSeek classes that match the call signatures used today:

- `DeepSeekContinuationMatcher`
- `DeepSeekArticleTranslator`
- `DeepSeekArticleSummarizerTagger`

These classes should return the existing result dataclasses or provider-neutral equivalents:

- `ArticleTranslationResult`
- `ArticleSummaryTagResult`

To avoid needless data model churn, the first implementation may keep these dataclasses in the current module or move them to a neutral module if the move is clean. The important boundary is that callers do not need to care whether the model is DeepSeek or Gemini.

Prompt contracts should remain strict:

- continuation matching returns `{"matches":[{"front_source_order":number,"back_source_order":number}]}`
- translation returns `content_type`, `classification_reason`, `translated_title_zh`, `translated_body_zh`
- summary/tagging returns `summary_zh` and `tags`

All three prompts must explicitly say JSON-only output, because DeepSeek's JSON mode requires the prompt to mention JSON output.

### Runtime Wiring

Update `worker.py` construction so:

- document parsing uses `DeepSeekContinuationMatcher` when DeepSeek is configured
- document/article enrichment uses `DeepSeekArticleTranslator` and `DeepSeekArticleSummarizerTagger`
- `provider_name` becomes `deepseek`
- `continuation_matcher_name` becomes `deepseek`
- model fields use `DeepSeekSettings.model`

Update `manage.py` for the same behavior in CLI commands:

- `phase3-parse-pdf`
- `phase3-parse-md`
- `phase3-persist-document`
- `phase3-enrich-article`

The existing Gemini enablement helpers should be replaced or generalized so runtime behavior checks DeepSeek configuration first.

### PDF Page Splitting

Add a PDF splitting boundary before MinerU submission.

Recommended module responsibility:

- input: source PDF path
- output: ordered one-page PDF files with 1-based physical page numbers

Recommended dependency:

- use an existing PDF library if already available in the environment or add one lightweight library explicitly through `requirements.txt`

The splitter should write deterministic artifacts under the current phase output root, for example:

```text
phase3-output/<document-stem>/pages/page-0001.pdf
phase3-output/<document-stem>/pages/page-0002.pdf
```

The implementation should not overwrite unrelated files outside that document-specific output directory.

### MinerU Batch Parsing For Page Files

Extend `MineruClient` with a batch page parsing entry.

Recommended shape:

```python
@dataclass(frozen=True)
class MineruParsedPage:
    page_number: int
    batch_id: str
    file_id: str
    file_name: str
    markdown_path: Path
    markdown_text: str

@dataclass(frozen=True)
class MineruParsedDocument:
    batch_id: str
    file_id: str
    file_name: str
    markdown_path: Path
    markdown_text: str
    pages: tuple[MineruParsedPage, ...] = ()
```

The current `MineruParsedDocument` shape can be extended rather than replaced, so existing tests and CLI paths can migrate incrementally.

New method:

```python
parse_pdf_by_pages(
    *,
    pdf_path: Path,
    output_root: Path,
    max_batch_size: int = 30,
) -> MineruParsedDocument
```

Behavior:

1. split the PDF into one-page PDF artifacts
2. group page files into chunks of up to 30
3. create one MinerU batch upload per chunk
4. upload all files in that batch
5. poll the batch until all submitted page files reach `done`
6. download and extract each page result zip
7. return pages sorted by `page_number`

The design uses batch width 30, not 30 independent whole-document jobs. This keeps request count lower while still allowing MinerU to process up to 30 page files as separate result units.

### Markdown Parsing With Page Context

Extend the parser to carry page context explicitly.

Recommended changes:

- `ArticleFragment` gains `page_number: int`
- `extract_article_fragments_from_mineru_markdown(...)` accepts `page_number: int | None`
- add a helper that accepts ordered page Markdown results and combines fragments:

```python
build_parse_result_from_mineru_pages(
    pages: Sequence[ParsedMarkdownPage],
    *,
    continuation_matcher=None,
) -> ParseResult
```

The helper should:

1. parse each page independently
2. assign global `source_order` across all fragments in page order
3. preserve each fragment's physical `page_number`
4. run continuation matching over continuation-bearing fragments
5. build final articles from fragments

When fragments merge, final article source pages are the sorted unique fragment page numbers in sequence order. A single-page article from page 3 has `[3]`; a cross-page article from page 1 and page 7 has `[1, 7]`.

### Persistence

The repository already has page-number persistence surfaces for fragments and final articles. The first implementation should reuse them.

Expected persistence behavior:

- `article_fragments.page_number` stores the fragment's 1-based physical PDF page number
- final article `source_page_numbers` stores sorted unique physical page numbers from its source fragments
- existing reader and workbench APIs keep exposing `source_page_numbers`

If implementation discovers existing storage assumes 0-based page indexes, update tests and code to normalize all newly parsed records to 1-based physical page numbers. Do not add a second competing page-number convention.

### Artifact Metadata

Whole-document parse runs currently store one MinerU batch id, file id, and Markdown path. Page-sliced parsing produces multiple batches and Markdown files.

For the first implementation:

- keep the existing parse-run source artifact fields populated with a compact summary:
  - `mineru_batch_id`: comma-separated batch ids or the first batch id plus a count suffix
  - `mineru_file_id`: original document stem or first page file id
  - `markdown_path`: a document-level merged Markdown file path
- write a merged debug Markdown file that concatenates pages with explicit separators:

```markdown
<!-- PDF_PAGE_NUMBER: 1 -->
...page 1 MinerU Markdown...

<!-- PDF_PAGE_NUMBER: 2 -->
...page 2 MinerU Markdown...
```

This preserves existing debug behavior while making page boundaries inspectable.

If later operations need per-page artifact drill-down in the UI, add a dedicated `parse_run_page_artifacts` table in a future slice.

## Data Flow

### Document Processing

1. Worker claims a pending document-processing run.
2. `persist_document_articles(...)` loads the source document.
3. `MineruClient.parse_pdf_by_pages(...)` splits and parses the PDF page-by-page.
4. Publication date is resolved from filename first, with merged Markdown fallback.
5. Parse run is created.
6. Source artifacts are updated with batch summary and merged Markdown path.
7. `build_parse_result_from_mineru_pages(...)` creates fragments and final articles with physical page numbers.
8. `record_parse_run_result(...)` persists fragments, matches, final articles, lineage, and page numbers.
9. Article processing runs are enqueued as they are today.

### Article Processing

1. Article worker claims article-processing runs as today.
2. DeepSeek translator classifies and translates.
3. Advertisement outputs still become `skipped_advertisement`.
4. Non-advertisement outputs continue to DeepSeek summary/tagging.
5. Existing enrichment persistence stores provider `deepseek` and the configured DeepSeek model.

### Continuation Matching

1. Page-aware fragments are built.
2. Continuation-bearing fragments are sent to DeepSeek.
3. DeepSeek returns source-order pairs.
4. Existing normalization accepts, ignores, or invalidates pairs.
5. Merged final article page numbers come from the paired fragments.

## Error Handling

### DeepSeek Errors

DeepSeek request failures should behave like current Gemini request failures:

- non-2xx status raises provider error
- malformed JSON raises provider error
- missing required fields raises provider error
- invalid content type raises provider error
- invalid tag counts raise provider error

These failures should be caught by the existing document/article processing state machines and persisted as retryable or terminal according to current step retry rules.

### MinerU Page Errors

A failed page inside a document should fail the document parse attempt for this slice.

Rationale:

- partial-page parse completion would produce silently incomplete newspapers
- existing document retry semantics can retry the whole parse attempt
- operators already have document-processing failure visibility

The implementation should record the failing page number in the error message where possible, for example:

```text
MinerU page parse failed for physical page 7: ...
```

### Batch Timeout

If a MinerU batch times out before all page files finish, the document parse run fails. The error message should include the batch id and unfinished page file names when available.

### Page Splitting Errors

If the PDF cannot be split, the document parse attempt fails before MinerU submission. This should be treated as a document processing failure, not a worker fatal error.

## Testing Strategy

### DeepSeek Unit Tests

Add tests covering:

- DeepSeek chat-completions URL and auth headers
- `response_format: {"type": "json_object"}` in requests
- continuation matching response parsing
- translation/classification response parsing
- summary/tag response parsing
- malformed response failures

### Runtime Wiring Tests

Add tests covering:

- worker document dependency construction uses DeepSeek classes
- worker article dependency construction uses DeepSeek classes
- CLI `phase3-enrich-article` passes `provider_name="deepseek"`
- CLI continuation matcher metadata uses `deepseek`
- `.env.example` and Compose expose DeepSeek settings

### MinerU Page-Slicing Tests

Add tests with fake splitter and fake MinerU transport or fake client:

- a 31-page PDF creates two MinerU batches of 30 and 1 page
- each parsed page result keeps its 1-based physical page number
- a failed page includes the page number in the error
- merged debug Markdown includes page separators

### Parser And Persistence Tests

Add tests covering:

- fragments parsed from page Markdown retain physical page numbers
- source orders remain global across pages
- single-page final articles expose `[page]`
- continuation-merged final articles expose `[front_page, back_page]`
- persisted article cards/details expose the 1-based page numbers

### Regression Tests

Run the full suite:

```bash
./.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

If available credentials allow live validation, run one controlled real PDF parse after unit tests pass. Live validation should not be required for ordinary CI-style tests.

## Rollout Plan

1. Add DeepSeek settings and provider-neutral chat helper.
2. Add DeepSeek continuation, translation, and summary/tag clients.
3. Switch worker and CLI construction to DeepSeek.
4. Add page splitting and MinerU page-batch parsing behind the existing document parse entry.
5. Add page-aware Markdown parsing and persistence normalization.
6. Update docs and example configuration.
7. Run full unit tests and one optional live parse if credentials are present.

## Implementation Notes

- Prefer extending existing dataclasses over replacing them when it keeps the migration small.
- Keep Gemini code available until a later cleanup slice.
- Avoid storing API keys in test snapshots, logs, or docs.
- Use 1-based page numbers everywhere for newly parsed documents.
- Keep batch size capped at 30 by default.
