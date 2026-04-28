# Newspaper Translator Progress Summary

Date: 2026-04-28

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion remains complete for the current repository goals.

Phase 3 has now moved beyond transient CLI-only parsing output and gained both a durable article persistence foundation and a first executable article enrichment slice.

The repository currently provides:

- a working Gmail-to-raw-PDF import path
- durable import-run and item-level audit history
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, and lineage persistence
- durable enrichment-run, enrichment-output, and ordered article-tag persistence
- executable Gemini-backed translation, summary, and tagging for one persisted article
- read-only CLI query surfaces for current visible article sets, enrichment results, and parse-run debug artifacts
- an initial scheduled-processing control plane with durable scheduler-run and document-processing state

## What Was Added On 2026-04-28

Implemented in:

- [article_enrichment.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_enrichment.py)
- [article_pipeline.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_pipeline.py)
- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
- [gemini.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/gemini.py)
- [pdf.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/pdf.py)
- [manage.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/manage.py)
- [0005_article_persistence_enrichment.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0005_article_persistence_enrichment.sql)

Current behavior:

- `phase3-persist-document` parses one imported raw PDF and persists a new parse run
- each parse run now stores raw fragments, continuation-match decisions, final articles, and article-to-fragment lineage
- publication date is persisted on both parse runs and final articles
- publication date is resolved first from the filename, then from parsed Markdown text
- missing publication date now fails the parse run instead of creating undated final articles
- `phase3-latest-articles` returns the visible article set for one imported document
- `phase3-parse-runs`, `phase3-parse-run-fragments`, `phase3-parse-run-matches`, and `phase3-parse-run-articles` expose parse history and debug artifacts through the CLI
- article enrichment now has repository helpers for loading one final article, creating versioned runs, persisting outputs, and querying the latest visible enrichment record
- `GeminiArticleTranslator` performs one strict-JSON translation call for `translated_title_zh` and `translated_body_zh`
- `GeminiArticleSummarizerTagger` performs one strict-JSON summary/tagging call for `summary_zh` and ordered `tags`
- `article_enrichment.py` orchestrates one enrichment run and records `succeeded`, `partial`, and `failed` outcomes
- `phase3-enrich-article` enriches one stored article through the CLI
- `phase3-latest-enrichment` returns the latest visible enrichment result for one article
- latest-visible rules now preserve older usable parse or enrichment results when a newer run fails
- the translation prompt now tells Gemini that the source may be a newspaper continuation fragment and instructs it to preserve jump markers rather than silently dropping them

Additional automatic-processing foundation implemented in:

- [document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/document_processing.py)
- [0006_scheduled_automatic_document_processing.sql](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/migrations/0006_scheduled_automatic_document_processing.sql)
- [test_document_processing.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_document_processing.py)
- [test_database.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_database.py)

Current automatic-processing behavior:

- `scheduler_runs` now persists one scheduler tick control-plane record with aggregate result counters
- `document_processing_runs` now persists one current-state automation record per `document_key`
- scheduler runs can now be created, finalized, and reloaded through one focused repository module
- document-processing state creation is idempotent for repeated initialization of the same document
- one eligible document can now be claimed safely without double claim
- eligible document ordering now prioritizes `manual_retry_requested` ahead of `pending`, then `failed_retryable`
- this slice is intentionally persistence-only so far; it does not yet execute parse or enrichment automatically

## Real Validation Notes

Validated against the local Wall Street Journal sample PDF:

- visually rendered the original PDF front page and page A7 to compare the source layout against MinerU `full.md`
- confirmed that the A1 article `Big Oil Explores Farther Afield To Dodge Middle East Turmoil` and the A7 continuation are present in the expected locations
- confirmed that continuation matching produces a merged persisted article when Gemini continuation matching is allowed to run with network access
- confirmed that the new enrichment path can execute a real Gemini run end to end against a persisted article

Observed quality notes:

- MinerU extraction is directionally correct for the validated article, but still includes newspaper-layout noise such as split words, glued continuation markers like `PleaseturntopageA7`, and occasional stray tokens
- Gemini translation quality is acceptable when the article has been merged correctly across pages
- for an unmerged fragment, the new `article-enrichment-v2` prompt prevents jump markers from being silently dropped, but Gemini currently translates markers such as `Please turn to page A7` into Chinese rather than preserving the original English string verbatim

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 103 tests in 3.547s
OK
```

Automatic-processing foundation spot checks:

```bash
python3 -m unittest tests.test_database tests.test_document_processing
```

```text
Ran 9 tests in 0.206s
OK
```

## Phase 3 Snapshot

Completed Phase 3 slices so far:

- MinerU PDF parsing through the batch upload API
- Markdown-to-article reconstruction
- explicit continuation-marker extraction
- optional Gemini continuation matching
- durable parse-run and final-article persistence
- fragment-level and match-level debug visibility
- enrichment persistence foundations and validation rules
- executable single-article Gemini enrichment with versioned translation, summary, and tags
- CLI read/write surfaces for persisted article enrichment
- durable scheduler-run and document-processing control-plane persistence
- single-document safe claim and eligible-document priority ordering for future automatic processing

Still not implemented:

- non-explicit continuation inference
- stronger cleanup and normalization for MinerU newspaper-layout noise before enrichment
- explicit protection rules for untranslated or verbatim-preserved continuation markers
- document-level or batch-level enrichment orchestration
- document failure-state transitions, recovery helpers, and manual retry mutation paths
- worker-driven background enrichment scheduling and retries
- dashboard routes or UI for browsing persisted article data
- post-processing for ads, notices, and other non-article content beyond current heuristics

## Suggested Next Step

The next automatic-processing slice should move from persistence into orchestration semantics: add document failure-state transitions, manual retry reactivation, and `process_document(...)` step execution with immediate retry before touching the long-running worker loop.
