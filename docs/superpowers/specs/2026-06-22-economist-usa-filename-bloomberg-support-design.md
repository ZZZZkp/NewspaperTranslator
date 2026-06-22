# Economist USA Filename, Issue-Level Dedupe, And Bloomberg Businessweek Support Design

Date: 2026-06-22

Related documents:

- [Publication Date, PDF Dedupe, And Source Name Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-07-publication-date-dedupe-and-source-name-design.md)
- [Economist Edition Parser Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-06-13-economist-edition-parser-implementation-plan.md)
- [MinerU Phase 3 Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-mineru-phase-3-design.md)
- [Cross-Page Continuation Matching Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-27-cross-page-continuation-matching-design.md)
- [Waterfall Card Hero Image Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-06-18-waterfall-card-hero-image-design.md)

## Overview

This design adds two capabilities to the Gmail-to-article pipeline:

1. **Economist USA filename adaptation.** The Economist now also arrives named like
   `The Economist USA - June 20 2026.pdf`. The underlying PDF is the same Calibre
   e-edition that the existing local parser already handles, so only filename-derived
   metadata is missing: the newspaper label (`经济学人`) and the publication date
   (`2026-06-20`).
2. **Issue-level deduplication for all publications.** The same issue can arrive under
   different filenames, from different senders, or with non-identical bytes. Today
   dedupe is content-hash only and misses these cases. Dedupe is extended to also
   collapse documents that share the same `(source_name, publication_date)` issue
   identity, keeping the first accepted copy authoritative.
3. **Bloomberg Businessweek support.** Bloomberg Businessweek (`Producer: pdf-lib`,
   no PDF bookmarks, image-heavy) routes through the existing MinerU path. It needs
   filename-derived metadata, recognition of Bloomberg's `►`/`◄` cross-page
   continuation markers, and confirmation that the existing MinerU image / hero-image
   flow populates its article cards.

## Goals

- Derive `source_name = 经济学人` and `publication_date = 2026-06-20` from
  `The Economist USA - June 20 2026.pdf`.
- Derive `source_name = 彭博商业周刊` and `publication_date = 2026-06-01` from
  `Bloomberg Businessweek USA - June 2026.pdf`.
- Support filename date forms `Month D YYYY` and `Month YYYY` (day defaults to `01`)
  in addition to the existing `YYYY-MM-DD` / `M-D` forms.
- Deduplicate documents by `(source_name, publication_date)` issue identity across all
  publications, in addition to the existing content-hash dedupe, keeping the first
  accepted copy authoritative.
- Stitch Bloomberg cross-page articles using the solid triangle markers `►` (continues
  to) and `◄` (continued from), without ever stitching on the white cross-reference
  triangles `▷` / `◁`.
- Confirm Bloomberg article cards receive a hero image through the existing MinerU
  image and `pick_largest_image` flow.

## Non-Goals

- Retrofitting or merging historical duplicate documents already in the database.
- Building a general publisher registry beyond a small explicit alias table for the
  publications we actually handle.
- Replacing the MinerU path with a custom Contents-page parser for Bloomberg.
- Extracting images for the Economist e-edition local path (not requested).
- Changing how content-hash dedupe behaves for byte-identical files.

## Current Behavior

- `detect_calibre_economist_edition` gates the local Economist parser on
  `Producer: calibre` + an outline TOC + an Economist signal. It is content-based, so a
  renamed Economist e-edition (`The Economist USA - June 20 2026.pdf`) already routes
  correctly to `parse_economist_edition`.
- `_extract_source_name_from_filename` in `ingestion.py` returns `经济学人` only for the
  `TE-YYYY-MM-DD-PDF_WEB` pattern; otherwise it strips a trailing date segment and
  returns the leading prefix verbatim.
- Import dedupe in `import_gmail_pdf_attachment` looks up an existing `documents` row by
  `content_hash` only. A duplicate reuses the canonical `document_key`, writes no second
  row, and re-ensures (does not duplicate) a `document_processing_run`.
- Publication date is resolved later by `resolve_publication_date` in
  `article_pipeline.py`: filename full date, filename month-day with Gmail-year
  completion, then markdown written/ISO date fallback.
- Cross-page stitching only fires for fragments that carry `continued_to_page` /
  `continued_from_page`. `_extract_continued_to_page` / `_extract_continued_from_page`
  in `pdf.py` recognize only WSJ-style textual markers (`please turn to page A4`,
  `continued from page A4`). FT / Guardian / Bloomberg carry no such textual markers, so
  they are never stitched today.
- The MinerU path already extracts page images into `article_images`, and the waterfall
  card hero-image feature selects the largest image via `pick_largest_image`.

## Data Model

### `documents`

Add one nullable column and one index:

- `issue_date TEXT` — the filename-derived publication date (`YYYY-MM-DD`) used as the
  issue identity for dedupe. Nullable because not every filename yields a date.
- index on `(source_name, issue_date)` to support the issue-identity lookup.

`issue_date` is the *filename-derived* date captured at import time. It is used only for
dedupe identity. The authoritative article `publication_date` continues to be resolved
during parsing (and may fall back to markdown when the filename has no date), so the two
can legitimately differ; `issue_date` being a best-effort hint is acceptable.

This change requires forward-only migration `0015`. No historical backfill or merge of
existing duplicate rows is performed.

### Import audit tables

Import-audit `source_name` usage continues to mean import transport and remains `gmail`.
Only `documents.source_name` carries the newspaper label.

## Filename Metadata Extraction (`ingestion.py`)

### Publisher alias table

Introduce a small explicit alias table mapping a normalized leading filename prefix to a
Chinese newspaper label. Matching is case-insensitive and prefix-based after the trailing
date segment is stripped:

- `The Economist USA` / `The Economist` → `经济学人`
- `Bloomberg Businessweek USA` / `Bloomberg Businessweek` → `彭博商业周刊`

The existing `TE-YYYY-MM-DD-PDF_WEB` special case continues to map to `经济学人`.

`_extract_source_name_from_filename` is extended so that, after isolating the leading
prefix, it consults the alias table. The longest matching alias wins (so
`The Economist USA` is preferred over `The Economist`). If no alias matches, behavior is
unchanged: return the leading prefix, or the full stem when no date segment is found.

### Filename date extraction

A filename date resolver supports, in priority order:

1. `YYYY-MM-DD` / `YYYY_M_D` (existing).
2. `M-D` / `MM-DD` with year completion from `source_message_internal_date`, else the
   current runtime year (existing).
3. `Month D YYYY` / `Month DD YYYY` written English form — `June 20 2026` → `2026-06-20`.
4. `Month YYYY` written English form with no day — `June 2026` → `2026-06-01`
   (day defaults to `01`).

Month-name parsing reuses the same month vocabulary and `Sept` normalization already
present in `_extract_written_date_from_text` (`article_pipeline.py`); that logic should
be shared rather than duplicated. Invalid dates (e.g. `June 31 2026`, `2-30`) yield no
date.

The resulting date is stored as `documents.issue_date` at import time.

## Issue-Level Deduplication (`ingestion.py`)

On every accepted PDF attachment:

1. Compute `content_hash`.
2. **Content lookup:** find an existing `documents` row by `content_hash`. If found,
   reuse the canonical `document_key` (current fast path, unchanged).
3. **Issue lookup:** else, if both `source_name` and `issue_date` are derivable, find an
   existing `documents` row with the same `(source_name, issue_date)`. If found, treat as
   a duplicate issue: reuse the canonical `document_key`, write no second `documents` row,
   write no second raw file, and re-ensure (do not duplicate) a `document_processing_run`.
4. **Insert:** else, insert a new `documents` row storing `source_name`, `issue_date`,
   and `source_message_internal_date`; write the raw PDF; ensure a
   `document_processing_run`.

The first accepted copy of an issue remains authoritative for `document_key`,
`source_name`, `original_filename`, `issue_date`, and `source_message_internal_date`.
Later same-issue arrivals are duplicate sightings only and never mutate the canonical row.

The content lookup and issue lookup run inside the existing `BEGIN IMMEDIATE`
transaction so concurrent imports stay deterministic.

### Assumption and risk

Issue dedupe assumes one issue per `(source_name, publication_date)`. Daily papers
(WSJ, FT) publish one issue per day, and magazines one per cover date, so this holds for
the publications in scope. If two genuinely distinct documents ever shared a source label
and date, issue dedupe would collapse them to the first; this is accepted per the
requirement, and the content-hash fast path still keeps byte-identical handling exact.

## Publication Date Resolution Alignment (`article_pipeline.py` and Economist path)

Both persist paths resolve the authoritative article `publication_date` preferring
`documents.issue_date` when present, then falling back to the existing markdown
written/ISO date resolution. Filename-derived dates remain authoritative over markdown.
The MinerU path (`persist_document_articles`) and the Economist edition path
(`persist_economist_edition_articles`) share this resolution so both populate
`publication_date` consistently for the new filename forms.

## Bloomberg Cross-Page Continuation (`pdf.py`)

### Markers

Bloomberg marks true cross-page continuations with **solid** triangles:

- `►N` (U+25BA, black right-pointing pointer) — this fragment continues *to* page `N`.
- `◄N` (U+25C4, black left-pointing pointer) — this fragment is continued *from* a prior
  page.

The **white** triangles `▷` (U+25B7) and `◁` (U+25C1) are "see page N" cross-references
(verified in the sample, e.g. `▷ 54`) and must never be treated as continuations.

### Extraction and merge

- `_extract_continued_to_page` additionally matches a solid `►` followed by a page number
  (e.g. `►84`) and returns the page token, while ignoring white triangles.
- `_extract_continued_from_page` additionally matches a solid `◄` followed by a page
  number and returns the page token.
- `_merge_fragment_body_text` additionally strips a trailing `►N` from the front fragment
  and a leading `◄N` from the back fragment when merging.

Fragments that gain `continued_to_page` / `continued_from_page` from these markers flow
through the existing DeepSeek continuation matcher unchanged; the matcher already requires
both endpoints to be set before accepting a pair.

### Validation risk

The `►` / `◄` glyphs must survive MinerU markdown extraction for this to work. If MinerU
renders them differently (e.g. as a different glyph, entity, or whitespace), the regex is
adjusted to the observed MinerU output. This must be validated against real MinerU output
for the Bloomberg sample, not only against raw `pypdf` text.

## Bloomberg Images

Bloomberg uses the existing MinerU image flow: MinerU extracts page images into
`article_images`, and the waterfall card hero-image feature selects the largest image via
`pick_largest_image` / `hero_image_url`. No new image logic is added. The work is to
verify the flow populates a hero image for Bloomberg articles end to end.

## Components And Boundaries

### `src/newspaper_translator/ingestion.py`

- Publisher alias table and alias-aware `source_name` extraction.
- Filename date extraction extended with `Month D YYYY` and `Month YYYY` forms.
- `issue_date` computed at import and stored on insert.
- Two-stage dedupe (content hash, then issue identity) inside the import transaction.

### `src/newspaper_translator/migrations/0015_documents_issue_date.sql`

- Add `documents.issue_date TEXT`.
- Add index on `(source_name, issue_date)`.

### `src/newspaper_translator/article_pipeline.py`

- Share month-name date parsing with the filename resolver.
- Prefer `documents.issue_date` in `resolve_publication_date`, keeping markdown fallback.

### `src/newspaper_translator/pdf.py`

- Solid-triangle continuation extraction and merge stripping, excluding white triangles.

## Data Flow

### Economist USA import

`The Economist USA - June 20 2026.pdf` → alias prefix `The Economist USA` → `source_name = 经济学人`
→ filename date `June 20 2026` → `issue_date = 2026-06-20` → dedupe (content, then issue)
→ insert or reuse → Calibre detection routes to `parse_economist_edition` → articles persist
with `publication_date = 2026-06-20`.

### Bloomberg import

`Bloomberg Businessweek USA - June 2026.pdf` → alias prefix `Bloomberg Businessweek USA`
→ `source_name = 彭博商业周刊` → filename date `June 2026` → `issue_date = 2026-06-01`
→ dedupe → insert or reuse → no Calibre, no bookmarks → MinerU path → fragments with
`►`/`◄` markers gain continuation endpoints → DeepSeek matcher stitches cross-page pairs →
articles persist with `publication_date = 2026-06-01` and a hero image from the largest
extracted image.

### Duplicate issue import

`content_hash` miss → `(source_name, issue_date)` hit → reuse canonical `document_key` →
no second `documents` row, no second raw file, no second processing run.

## Error Handling

- Filename with no derivable date: `issue_date` is null; dedupe falls back to content
  hash only; article `publication_date` falls back to markdown resolution as today.
- Invalid filename date (`June 31 2026`, `2-30`): treated as no date.
- Issue dedupe runs only when both `source_name` and `issue_date` are present.
- Bloomberg fragments without `►`/`◄` markers simply are not stitched (current behavior
  for unmarked publications).

## Logging

- `source_name` and `issue_date` derived at import, with the matched alias (if any).
- Dedupe decision: `content_hash_reuse`, `issue_identity_reuse`, or `new_document`,
  including the canonical `document_key` on reuse.
- Continuation marker extraction source (`triangle` vs `wsj_textual`) for observability.

## Testing

### Filename source name

- `The Economist USA - June 20 2026.pdf` → `经济学人`.
- `Bloomberg Businessweek USA - June 2026.pdf` → `彭博商业周刊`.
- Existing `TE-2026-06-13-PDF_WEB.pdf` → `经济学人` (unchanged).
- Existing `wsj-2026-05-06.pdf` → `wsj`; `金融时报-5-6.pdf` → `金融时报` (unchanged).

### Filename date

- `June 20 2026` → `2026-06-20`.
- `June 2026` → `2026-06-01`.
- `June 31 2026` → no date.
- Existing `YYYY-MM-DD` and `M-D` (with Gmail-year completion) cases unchanged.

### Issue dedupe

- Same issue under two different filenames / non-identical bytes → one canonical document.
- Byte-identical content still deduped via content hash (unchanged).
- Duplicate issue import creates no second `document_processing_run`.
- Duplicate issue import does not overwrite the first document's `source_name` or
  `original_filename`.
- A document with no derivable `issue_date` is not issue-deduped against another.

### Continuation markers

- `►84` sets `continued_to_page`; `◄` sets `continued_from_page`.
- `▷ 54` and `◁` are ignored (no continuation endpoint set).
- Merge strips trailing `►N` / leading `◄N`.

### Routing

- `The Economist USA - June 20 2026.pdf` (Calibre) still routes to the Economist edition
  parser, not MinerU.
- A Bloomberg-shaped (`pdf-lib`, no outline) PDF still routes to the MinerU path.

## Migration Strategy

Forward-only migration `0015`:

1. Add `documents.issue_date TEXT`.
2. Add index on `(source_name, issue_date)`.

No automatic cleanup or merge of historical duplicate documents. Existing rows have a null
`issue_date` and are unaffected; issue dedupe applies to newly imported documents.

## Acceptance Criteria

- `The Economist USA - June 20 2026.pdf` imports with `source_name = 经济学人` and resolves
  `publication_date = 2026-06-20`, parsed via the existing Calibre edition path.
- `Bloomberg Businessweek USA - June 2026.pdf` imports with `source_name = 彭博商业周刊`,
  resolves `publication_date = 2026-06-01`, parses via MinerU, stitches `►`/`◄` cross-page
  articles, and shows a hero image on its cards.
- White-triangle `▷` / `◁` cross-references never cause article stitching.
- The same issue arriving under different filenames or non-identical bytes produces a
  single canonical document with no duplicate processing run.
- Byte-identical content dedupe behavior is unchanged.
- Import-audit APIs continue to expose `gmail` as the import source.
