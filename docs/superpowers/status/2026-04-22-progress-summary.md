# Newspaper Translator Progress Summary

Date: 2026-04-22

## Current Stage

The project has moved from planning into executable TDD-based implementation.

The codebase now contains:

- A project-local Python virtual environment workflow
- A minimal Python application structure under `src/newspaper_translator`
- A growing test suite under `tests`
- A minimal Docker runtime skeleton
- A first real PDF adapter validated against sample newspaper files

## Implemented Foundations

### Configuration

Implemented in:

- [config.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/config.py)
- [test_config.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_config.py)

Current behavior:

- Loads required application settings from environment variables
- Fails fast when required Gmail credentials are missing

### Document Identity

Implemented in:

- [documents.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/documents.py)
- [test_documents.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_documents.py)

Current behavior:

- Builds a stable document key from message id, attachment id, and content hash
- Produces the same logical key for repeated imports of the same attachment

### Task State Machine

Implemented in:

- [tasks.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/tasks.py)
- [test_tasks.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_tasks.py)

Current behavior:

- Creates tasks in `pending`
- Supports `pending -> running -> succeeded`
- Rejects illegal transition from `succeeded` back to `running`

### Ingestion Boundary

Implemented in:

- [ingestion.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/ingestion.py)
- [test_ingestion.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_ingestion.py)

Current behavior:

- Selects only Gmail messages from configured senders with PDF attachments
- Creates a `pending` document-processing task after a successful import boundary

## Docker Runtime Skeleton

Implemented in:

- [Dockerfile](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/Dockerfile)
- [docker-compose.yml](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docker-compose.yml)
- [.env.example](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/.env.example)
- [requirements.txt](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/requirements.txt)
- [test_container_scaffolding.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_container_scaffolding.py)

Current behavior:

- Repository includes `web`, `worker`, and `db` service definitions
- Container configuration validates with `docker compose config`
- Python runtime dependency `pypdf` is recorded for both local and container use

This is still a scaffold, not a finished runtime. It is enough to support continued TDD work against the target deployment shape.

## Real PDF Sample Coverage

The following real samples are now used in automated tests:

- [/Users/pzk/workspace/NewspaperTranslator/华尔街日报-4-20.pdf](/Users/pzk/workspace/NewspaperTranslator/华尔街日报-4-20.pdf)
- [/Users/pzk/workspace/NewspaperTranslator/卫报-4-21.pdf](/Users/pzk/workspace/NewspaperTranslator/卫报-4-21.pdf)
- [/Users/pzk/workspace/NewspaperTranslator/金融时报-4-20.pdf](/Users/pzk/workspace/NewspaperTranslator/金融时报-4-20.pdf)

Implemented in:

- [pdf.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/pdf.py)
- [test_pdf_inspection.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_pdf_inspection.py)

Current behavior:

- Reports page counts for the three sample PDFs
- Detects whether a document has extractable text
- Classifies the samples as first-pass `digital` or `scanned`
- Extracts page text from digital samples
- Returns empty page text for the current scanned sample
- Builds page-level profiles for every page
- Extracts text pages only for pages with extractable text
- Extracts simple line-based text blocks from digital pages
- Extracts first-pass title candidates from digital sample pages

Current observed sample outcomes:

- `华尔街日报-4-20.pdf`: 36 pages, classified as `digital`
- `卫报-4-21.pdf`: 40 pages, classified as `digital`
- `金融时报-4-20.pdf`: 28 pages, classified as `scanned`

## Test Status

Current test command:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current result at the time of this summary:

```text
Ran 20 tests in 31.389s
OK
```

## What This Enables Next

The project is now ready to continue into the first article-reconstruction slice.

The most natural next steps are:

1. Group title candidates and nearby text blocks into article fragments on digital samples.
2. Introduce explicit page/document parsing artifacts for later persistence.
3. Add an OCR boundary for scanned samples while keeping the same downstream page/article interfaces.
4. Evolve the Docker scaffold from static validation into a startable local stack with real app commands.

## Important Constraint

The current page structuring logic is intentionally minimal:

- Text blocks are line-based, not coordinate-aware layout blocks.
- Title candidates are heuristic and recall-oriented.
- No article reconstruction, OCR, translation, tagging, or dashboard runtime exists yet.

That is expected at this stage. The main achievement is that the repository now has a real, tested parsing entrypoint grounded in real sample files rather than only design documents.
