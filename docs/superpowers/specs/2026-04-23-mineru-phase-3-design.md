# MinerU Phase 3 Parsing Design

Date: 2026-04-23

Reference:

- [MinerU API docs](https://mineru.net/apiManage/docs)

## Overview

This document defines how Phase 3 should migrate from local PDF extraction experiments to the MinerU precision parsing API.

Implementation note as of 2026-04-27:

- the MinerU client, configuration, and PDF batch parsing path are implemented
- `full.md` extraction is implemented and used as the Phase 3 parsing boundary
- a direct Markdown parsing entrypoint is also implemented for local debugging
- the current article reconstruction is intentionally heuristic and does not yet perform LLM-based advertisement or statement filtering

The main decision is:

Use MinerU precision parsing as the primary extraction boundary for Phase 3, and consume the returned Markdown output as the upstream input to article reconstruction.

## Why MinerU

The current repository can already inspect PDFs locally with `pypdf`, but that is not the best long-term boundary for newspaper parsing.

The target inputs include:

- multi-column digital newspaper pages
- scanned or mixed-quality newspaper pages later
- layout-heavy pages where drawing-order text extraction is weak

MinerU is a better fit because the official precision parsing API already provides:

- a parser designed for complex document layouts
- OCR-capable parsing options
- structured parsing outputs distributed as a result zip
- a `full.md` artifact that can become the canonical Phase 3 parsing input

## Selected API Path

The chosen integration path is the local-file batch upload flow, not the single-file URL flow.

Reason:

- this project stores PDFs locally after Gmail import
- the single-file `extract/task` API accepts file URLs and the documentation states it does not support direct file upload
- the documented batch upload path is designed for local files and automatically submits parsing after upload

Selected flow:

1. call `POST /api/v4/file-urls/batch`
2. receive upload targets and a `batch_id`
3. upload the local PDF file to the returned URL with `PUT`
4. poll `GET /api/v4/extract-results/batch/{batch_id}`
5. wait until the file result reaches `done`
6. download `full_zip_url`
7. extract `full.md`
8. hand off Markdown to the repository's Phase 3 parsing entry

## Integration Boundaries

### `mineru.py`

This module should own all MinerU API interaction:

- request construction
- authentication headers
- upload orchestration
- polling
- result download
- zip extraction

It should not own Gmail import logic or article reconstruction rules.

### `config.py`

This module should expose explicit MinerU settings and fail fast when the MinerU path is requested without required credentials.

### `pdf.py`

This module should stop being the intended primary parsing source.

It may remain useful for:

- fixture inspection
- fallback behavior
- local debugging

But the Phase 3 primary entry should move to Markdown produced by MinerU.

### Future Markdown Parser Module

The repository should add a Markdown-driven parser boundary that:

- reads `full.md`
- extracts article candidates
- normalizes them into repository-native article objects

That logic should stay separate from the network client.

Status on 2026-04-27:

This boundary currently lives in `pdf.py` through `extract_articles_from_mineru_markdown()` and is exposed by the `phase3-parse-md` CLI command. It can already reconstruct basic title/body article structures, merge byline headings, and skip obvious teaser-style digest blocks.

## Data And Runtime Flow

1. Gmail import persists the raw PDF locally.
2. Phase 3 parser hands the local PDF path to the MinerU adapter.
3. The MinerU adapter uploads the file, polls the batch result, downloads the result zip, and extracts `full.md`.
4. A Markdown parser converts `full.md` into page and article structures.
5. Downstream enrichment will later consume those article structures.

## Configuration

Planned environment variables:

- `MINERU_API_TOKEN`
- `MINERU_MODEL_VERSION`
- `MINERU_LANGUAGE`
- `MINERU_ENABLE_OCR`
- `MINERU_ENABLE_TABLE`
- `MINERU_ENABLE_FORMULA`
- `MINERU_POLL_INTERVAL_SECONDS`
- `MINERU_POLL_TIMEOUT_SECONDS`

Recommended defaults:

- model version: `vlm`
- language: `ch`
- OCR: `false`
- table: `true`
- formula: `true`

## Failure Semantics

The MinerU adapter should surface failures clearly and separately:

- configuration errors
- upload request failures
- file upload failures
- polling timeout
- completed result without `full_zip_url`
- zip download failures
- zip payload missing `full.md`

The first implementation can fail the parse call directly.
Retry orchestration can be added later at the task or worker level.

Status on 2026-04-27:

The current MinerU client already retries transient upload and polling transport failures and fails clearly on missing `full.md`, missing result URLs, and polling timeout.

## Testing Strategy

The MinerU client should be implemented with TDD and fake HTTP boundaries.

The first test sequence should be:

1. settings load MinerU configuration
2. settings fail when required MinerU token is missing
3. client requests a batch upload target for one local PDF
4. client uploads the file to the returned URL
5. client polls until the batch file reaches `done`
6. client downloads the result zip and extracts `full.md`
7. Phase 3 entry builds article-oriented output from extracted Markdown

## Migration Rule

During migration:

- existing `pypdf` parsing tests may remain
- new Phase 3 entry work should target MinerU output first
- local PDF parsing should not keep growing as the main architecture

This keeps the repository moving toward the chosen production parsing boundary instead of deepening an exploratory fallback path.

## Remaining Scope After The Current Implementation

The current implementation leaves these responsibilities for later phases:

- LLM-based filtering of advertisements, corrections, statements, and other non-article content
- better cross-page continuation cleanup
- richer article metadata beyond title and body
