# Newspaper Translator Progress Summary

Date: 2026-04-28

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion remains complete for the current repository goals.

Phase 3 has now moved beyond transient CLI-only parsing output and gained a durable article persistence foundation.

The repository currently provides:

- a working Gmail-to-raw-PDF import path
- durable import-run and item-level audit history
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, and lineage persistence
- durable enrichment-run, enrichment-output, and ordered article-tag storage foundations
- read-only CLI query surfaces for current visible article sets and parse-run debug artifacts

## What Was Added On 2026-04-28

Implemented in:

- [article_pipeline.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_pipeline.py)
- [article_store.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/article_store.py)
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
- enrichment history now has tables and repository functions for runs, structured outputs, and ordered tags
- latest-visible rules now preserve older usable parse or enrichment results when a newer run fails

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result:

```text
Ran 94 tests in 3.419s
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

Still not implemented:

- actual enrichment job orchestration that calls an LLM provider for translation, summary, and tags
- non-explicit continuation inference
- dashboard routes or UI for browsing persisted article data
- post-processing for ads, notices, and other non-article content beyond current heuristics

## Suggested Next Step

The next Phase 3 milestone should hook a real enrichment job onto persisted final articles so the repository can populate Chinese titles, summaries, translations, and tags into the new versioned enrichment tables.
