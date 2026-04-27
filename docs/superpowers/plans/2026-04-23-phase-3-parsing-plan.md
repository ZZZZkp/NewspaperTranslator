# Phase 3 Parsing Plan

Date: 2026-04-23

Related documents:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)
- [MinerU Phase 3 Parsing Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-mineru-phase-3-design.md)
- [Newspaper Translator Progress Summary](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/status/2026-04-23-progress-summary.md)
- [MinerU API docs](https://mineru.net/apiManage/docs)

## Goal

Phase 3 should turn imported newspaper PDFs into article-oriented structures by using MinerU precision parsing as the primary extraction path.

## Implementation Status

As of 2026-04-27, the following slices are implemented:

- MinerU configuration loading from environment
- MinerU batch upload, polling, zip download, and `full.md` extraction
- a PDF-facing CLI entry: `phase3-parse-pdf`
- a Markdown-facing CLI entry: `phase3-parse-md`
- initial Markdown-to-article reconstruction with tests for subtitle, byline, and teaser filtering

The main remaining parsing gaps are now:

- LLM-based advertisement and statement filtering after Markdown reconstruction
- stronger cross-page cleanup and continuation stitching
- downstream enrichment and presentation work

The Phase 3 primary path is now:

1. submit local raw PDFs to MinerU through the documented batch upload flow
2. wait for a completed extract result
3. download the returned result zip
4. extract `full.md`
5. convert MinerU Markdown output into article-oriented parsing objects

## Why The Plan Changed

The repository started Phase 3 with local `pypdf` extraction experiments because they were fast to bootstrap and easy to test offline.

That path was useful as a spike, but it is not the best main strategy for the actual target problem:

- newspaper layouts are multi-column and noisy
- scanned inputs are expected later
- Markdown output from a dedicated parser is a stronger input to article reconstruction than raw line dumps
- the official MinerU API already supports a precision parsing workflow that fits this project better

The local `pypdf` helpers should remain available as a fallback and as a test baseline during the migration, but they are no longer the intended primary Phase 3 route.

## Current Starting Point

The repository already provides:

- imported raw PDFs stored locally from Gmail
- real sample PDF coverage in tests
- local PDF inspection helpers in [pdf.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/pdf.py)
- early same-page parsing experiments for headlines, blocks, and article candidates

The repository now also provides:

- MinerU API configuration
- MinerU upload and polling client code
- zip download and `full.md` extraction
- Markdown-driven article parsing
- runtime entrypoints that use MinerU PDF output or direct Markdown as the Phase 3 source of truth

## Recommended Delivery Order

### Slice 1: MinerU Configuration

Add explicit configuration for:

- API token
- model version
- parser options
- polling interval and timeout

This slice should fail fast when MinerU is enabled but credentials are missing.

### Slice 2: MinerU Batch Upload Client

Implement the documented local-file path:

1. request upload URLs with `POST /api/v4/file-urls/batch`
2. upload the local PDF to the returned URL with `PUT`
3. capture the returned `batch_id`

This slice should stay focused on one file and one batch path first.

### Slice 3: Result Polling And Markdown Extraction

Poll `GET /api/v4/extract-results/batch/{batch_id}` until completion.

When the file reaches `done`:

- download `full_zip_url`
- extract `full.md`
- return a local parsing result object that points at the extracted Markdown

### Slice 4: Markdown Parsing Entry

Add a Phase 3 parsing entrypoint that reads MinerU Markdown and converts it into repository-native structures.

The first version only needs to support:

- page-level Markdown loading
- basic article splitting
- title and body extraction

Status on 2026-04-27: completed for the first usable parser version, with `phase3-parse-md` added for direct local Markdown debugging.

### Slice 5: Phase 3 Runtime Switch

Move the primary Phase 3 path to MinerU-backed Markdown parsing.

The current local `pypdf` helpers should remain in place for:

- test fixtures
- fallback behavior
- debugging comparisons

Status on 2026-04-27: completed for the current CLI path. `phase3-parse-pdf` now uses MinerU output as the primary parse source.

### Slice 6: Debug Artifacts

Persist inspectable parsing artifacts for one imported PDF:

- MinerU batch metadata
- extracted `full.md`
- parsed article JSON or text summaries

## TDD Queue

Every slice should follow the same loop:

1. add one failing test
2. run the narrowest possible test target and verify RED
3. add the minimum implementation to reach GREEN
4. rerun the targeted tests
5. refactor while staying green

Recommended first tests:

1. `loads MinerU settings from environment`
2. `fails fast when MinerU token is missing for MinerU parsing`
3. `creates a MinerU batch upload request for a local PDF`
4. `polls MinerU until a batch file reaches done`
5. `downloads the result zip and extracts full md`
6. `builds a page article from MinerU markdown`

## Success Criteria

We should consider the MinerU migration meaningfully underway when the repository can:

- submit one local sample PDF to MinerU
- wait for completion and download the result zip
- extract `full.md`
- produce at least one usable article-oriented output from that Markdown

## What We Are Not Doing Yet

- cross-page continuation from MinerU output
- LLM-based advertisement and statement filtering
- dashboard-facing rendering
- enrichment, translation, and tagging
- production scheduling around the new parser path
