# Newspaper Translator Progress Summary

Date: 2026-05-02

## Current Stage

Phase 1 foundation work remains complete.

Phase 2 Gmail ingestion remains complete for the current repository goals.

Phase 3 backend processing remains on the article-stage retry model introduced in the previous milestone.

The repository has now started the product-facing article-processing workbench slice on top of that backend.

The repository currently provides:

- a working Gmail-to-raw-PDF import path
- durable import-run and item-level audit history
- MinerU-backed Markdown article reconstruction
- explicit Gemini-assisted continuation matching for continuation-marked fragments
- durable parse-run, fragment, continuation-match, final-article, image, and enrichment persistence
- a long-running worker loop with overdue catch-up scheduling
- document-level parse persistence through one shared control-plane path
- durable logical `article_key` identity across repeated parses of the same source document lineage
- scheduler-driven article-stage execution and stale-run recovery
- article-stage CLI and web/API entry points for status inspection and manual retry
- a reading dashboard and document-processing operator workbench in the standalone frontend
- a new article-processing list contract shaped for frontend card rendering
- article-processing list filtering by status, source, and publication-date range
- a frontend workbench split between `文档处理` and `文章处理`
- a frontend article-processing detail page with retry and cross-navigation actions

## What Was Added On 2026-05-02

Implemented in:

- [api/queries.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/api/queries.py)
- [web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/web.py)
- [frontend/index.html](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/index.html)
- [frontend/app.js](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/frontend/app.js)
- [test_api_queries.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_api_queries.py)
- [test_frontend_static.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_frontend_static.py)
- [test_web.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests/test_web.py)
- [2026-05-02-article-processing-workbench-design.md](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-02-article-processing-workbench-design.md)
- [2026-05-02-article-processing-workbench-implementation-plan.md](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-05-02-article-processing-workbench-implementation-plan.md)

Current behavior:

- `list_article_processing_card_views(...)` now exposes a UI-ready article-processing list shape
- `/api/article-processing` now returns article title, document key, source name, original filename, publication date, source page numbers, current step, failure count, and latest error summary
- `/api/article-processing` now supports:
  - `status`
  - `source`
  - `publication_date_from`
  - `publication_date_to`
- the frontend operator workbench now has internal tabs for:
  - `文档处理`
  - `文章处理`
- the frontend now supports `#articles-processing` as a dedicated article-processing list route
- the frontend now supports `#article-processing/<article_key>` as an independent article-processing detail route
- the article-processing list now loads from `/api/article-processing` and renders operator-facing cards
- the article-processing list now supports status, source, and date-range filters in the sidebar
- the article-processing detail page now shows:
  - status summary
  - state badges
  - latest error summary
  - article identity fields
  - runtime fields such as lock state and last success input hash
- the article-processing detail page now supports:
  - manual retry
  - jump to owning document detail
  - jump to article reading detail
- the article-processing retry button now disables while the item is `running`

## Current Test Status

Current command:

```bash
./.venv/bin/python -m unittest tests.test_api_queries tests.test_web tests.test_frontend_static
```

Current result:

```text
Ran 40 tests in 1.750s
OK
```

Key new TDD verification added today:

- query test proving article-processing list cards expose the operator-facing fields needed by the frontend
- query test proving article-processing list cards support source and publication-date filtering
- web test proving `/api/article-processing` returns the expanded card contract
- web test proving `/api/article-processing` preserves status filtering
- web test proving `/api/article-processing` supports source and publication-date filtering
- frontend static test proving the workbench now includes `文档处理 / 文章处理` tabs
- frontend static test proving article-processing list and detail sections exist in the shell
- frontend static test proving article-processing filter controls and detail actions are wired into `app.js`

## Article-Processing Workbench Snapshot

Completed slices from the approved article-processing workbench plan so far:

- frontend-facing article-processing list contract
- article-processing list route and workbench tab foundations
- article-processing list rendering
- article-processing filtering by status, source, and date
- independent article-processing detail route and page shell
- article-processing manual retry wiring
- article-processing navigation to document detail and article reading detail
- detail-page runtime field and status-badge rendering

Not completed yet in this milestone:

- browser-driven manual QA of the new workbench interactions
- broader UI polish for tab transitions, empty states, and operator readability
- deeper frontend regression coverage beyond the current static-shell and API tests

## Suggested Next Step

The next meaningful slice is to run the new article-processing workbench in the browser, validate the end-to-end interaction flow, and then spend one small polish pass on route transitions, button states, and operator readability issues discovered during manual QA.
