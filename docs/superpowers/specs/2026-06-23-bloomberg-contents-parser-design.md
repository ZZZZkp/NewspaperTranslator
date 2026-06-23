# Bloomberg Businessweek Contents-Page Parser Design

Date: 2026-06-23

Related documents:

- [Economist USA Filename, Issue Dedupe, And Bloomberg Support Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-06-22-economist-usa-filename-bloomberg-support-design.md)
- [Economist Edition Parser Implementation Plan](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/plans/2026-06-13-economist-edition-parser-implementation-plan.md)
- [Waterfall Card Hero Image Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-06-18-waterfall-card-hero-image-design.md)

## Overview

The current Bloomberg Businessweek path routes the magazine through MinerU, which
over-fragments it: a live parse produced 141 "articles" for a ~35-article monthly, where
107 fragments (bylines, captions, pull-quote sidebars, product blurbs, table-of-contents
fragments) were classified as `article` and shown as separate cards. The MinerU markdown
also drops the magazine's graphical continuation markers, so cross-page stitching never
fires.

This design replaces the Bloomberg parsing route with a local **Contents-page parser**
(`bloomberg_edition.py`), a sibling to `economist_edition.py`. Instead of PDF bookmarks
(which Bloomberg lacks), article boundaries come from the magazine's printed **Contents
page** combined with a detected printed-to-physical page-number offset. This collapses the
141 fragments into ~35 Contents-aligned article cards, absorbs ads and fillers into the
enclosing article rather than emitting them as cards, and sidesteps the continuation-marker
problem entirely (range absorption handles jumps).

## Goals

- Parse Bloomberg Businessweek locally from its Contents page, producing one article per
  Contents entry, spanning that entry's start page to the next entry's start page.
- Detect the printed-to-physical page offset robustly (observed constant `+2`, voted across
  detected folios) and map Contents folios to physical PDF pages.
- Extract each article's body text and embedded images from its physical page range, so the
  existing image-extraction and hero-image flow populates waterfall cards.
- Route Bloomberg PDFs to this parser; fall back to the existing MinerU path whenever the
  Contents page cannot be parsed reliably.
- Keep `source_name = 彭博商业周刊` and `publication_date = 2026-06-01` (already provided by
  the filename logic shipped in the prior design).

## Non-Goals

- Stripping full-page advertisement pages from absorbed article text (deferred to v2; v1
  absorbs ad text as minor noise — the win is collapsing the card count).
- A generalized reusable magazine Contents-parser framework (Bloomberg-only; YAGNI).
- Changing the MinerU path itself, or the enrichment-stage advertisement classifier.
- Re-implementing image storage; the parser embeds image references and reuses the existing
  persistence path.
- Cross-page `►`/`◄` stitching for Bloomberg (range absorption makes it unnecessary; the
  markers also do not survive MinerU and are not in the Contents path).

## Current Behavior

- `document_processing._build_parse_persist_callback` routes: if
  `detect_calibre_economist_edition` → `persist_economist_edition_articles`; otherwise
  `persist_document_articles` (MinerU). Bloomberg (`Producer: pdf-lib`, no outline) falls
  through to MinerU.
- `persist_economist_edition_articles` (`article_pipeline.py`) accepts a `parse_edition`
  callable returning a `ParsedEdition` (`.parse_result`, `.debug_text`), resolves the
  publication date (preferring `documents.issue_date`), and calls `record_parse_run_result`.
- `record_parse_run_result` → `article_store` persists `final_articles` and, via
  `extract_local_image_paths_and_clean_text`, pulls `![](path)` image references out of each
  article body into `article_images`. The waterfall hero-image feature selects the largest
  via `pick_largest_image`.
- The Economist local path embeds no image references, so it stores no images; that is
  acceptable for the Economist but Bloomberg requires images.

## Architecture

A new module `src/newspaper_translator/bloomberg_edition.py` owns Bloomberg detection and
parsing, mirroring `economist_edition.py`. It exposes:

- `detect_bloomberg_edition(pdf_path) -> bool`
- `parse_bloomberg_edition(pdf_path) -> ParsedEdition`

Routing in `document_processing._build_parse_persist_callback` becomes: Calibre Economist →
**Bloomberg** → MinerU. Persistence reuses the Economist persist routine parameterized with
the Bloomberg parser, parser name, and version (a thin `persist_bloomberg_edition_articles`
wrapper, or a direct call with `parse_edition=parse_bloomberg_edition`).

### Why this route

- Bloomberg has no PDF outline, but it has a rich printed Contents page and a stable printed
  page-number scheme, which together give reliable article boundaries.
- Local parsing is fast, free, and deterministic, and avoids MinerU's magazine
  over-fragmentation.
- Reusing the Economist persist + image-extraction path keeps new code small and focused.

## Contents-Page Detection And Parsing

### Locating the Contents page

Scan the first ~15 pages for the page whose text contains a `Contents` heading and several
lines ending in a small integer (the entry folios). The first such page is the Contents page
(physical page 10 / 0-based index 9 in the sample).

### Parsing entries

Each Contents entry is a line of the form `[section] title … folio`:

- The trailing integer on a line is the candidate **folio**.
- Accept a folio only if it is within `[1, max_printed_folio]` and the folios form a
  **non-decreasing** sequence (10, 15, 19, 20, 23, …, 108 in the sample). This monotonic +
  range rule naturally excludes the footer ("How to contact …", phone numbers like
  `212 617-2900`), which does not end in a plausibly-increasing folio.
- **Wrapped titles:** a line with no trailing folio is a continuation of the current entry;
  join it with following lines until a folio appears (e.g. `United's CEO is fighting turf
  wars—and` + `courting influencers 84`).
- **Section labels:** a known set `{Remarks, In Context, In View, Pursuits, Exit Strategy}`
  appearing at the start of a section's first entry is split off and stored as `section`,
  carried forward to subsequent entries until the next known label. The cover-feature label
  (e.g. `The AI Issue`, which changes each issue) is not in the set and remains part of the
  title; this is acceptable for v1.

Each parsed entry yields `(section, title, folio)`.

## Page-Number Offset And Article Ranges

### Offset detection

Bloomberg prints its folio as `Bloomberg Businessweek <N>` in the page text. For each page
where this marker is found, compute `physical_1based - printed_N`. Take the **mode** across
all detections as the offset; discard outliers. In the sample this is a constant `+2` across
all 36 detected pages. If fewer than a small threshold of pages yield an offset, or the
detections do not agree on a dominant value, treat detection as failed and fall back to
MinerU.

### Ranges

- For each entry: `physical_start = folio + offset`.
- Sort entries by folio; each article spans `[physical_start, next_entry_physical_start)`,
  the last spanning to `total_pages + 1`.
- Pages before the first entry's `physical_start` (cover, masthead, contributors, the
  Contents page, early ads) are dropped.

### Title cross-check

For each entry, look for the first several title words on its mapped `physical_start` page
(±1 page). On a hit, snap the start to where the title appears and log a confirmation. On a
miss, keep the offset-derived start and log a warning; do not fail the entry. (Mirrors the
Economist's per-article marker cross-check.)

## Text And Image Extraction Per Article

### Body text

Extract text from each page in the article's physical range with `pypdf` and apply light
cleaning:

- Drop the running header `Bloomberg Businessweek <N>`.
- Drop standalone `ADVERTISEMENT` marker lines.
- Collapse excessive blank lines.

Ad and filler pages inside the range are absorbed into the article body as minor text noise
(v1 does not detect or strip full-page ad pages).

### Images

For each page in the range, extract embedded raster images with `pypdf` (`page.images`),
write them to `output_root/<pdf-stem>/images/` using the same relative-path convention the
MinerU path uses, and embed an `![](relative/path.jpg)` reference for each into the article's
`body_text`. Downstream persistence extracts these into `article_images`, and the largest
becomes the card hero.

## Persistence And Integration

`parse_bloomberg_edition` returns a `ParsedEdition` whose `parse_result` contains one
standalone article per Contents entry (built like the Economist edition: one fragment, one
`ParsedArticle` each), with each `body_text` carrying cleaned text plus embedded image
references, and a merged `debug_text` artifact.

Persistence reuses `persist_economist_edition_articles`'s structure with
`parse_edition=parse_bloomberg_edition`, `parser_name="bloomberg-edition"`, and
`parser_version=BLOOMBERG_EDITION_PARSER_VERSION`. Because `record_parse_run_result` already
extracts `![](path)` references into `article_images`, the hero-image flow works without new
storage code. Publication date resolution already prefers `documents.issue_date`.

## Detection And Fallback

`detect_bloomberg_edition(pdf_path)` returns true only when all hold (else false → MinerU):

1. `Producer` contains `pdf-lib` (or another non-Calibre signal), and page text contains
   `Bloomberg Businessweek`.
2. A Contents page is found.
3. The Contents page yields at least a threshold number of valid entries (e.g. ≥ 8).
4. A dominant printed-to-physical offset is detected.

Any `pypdf` read error or unmet condition results in `False`, routing to MinerU. This keeps
a future issue with an unexpected layout from producing empty or broken output.

## Error Handling

- Contents page not found, too few entries, or no dominant offset → detection returns false
  → MinerU fallback (no Bloomberg-edition parse run is created).
- Title cross-check miss → log a warning, keep offset-derived start, continue.
- An article range that extracts no text → skip that article (as the Economist path does).
- Image extraction failure for a page → skip that image, continue (images are best-effort).

## Logging

- Contents page index, number of entries parsed, detected offset and its vote distribution.
- Per-article: title, section, folio, physical range, image count, and title cross-check
  result (`matched` / `offset_only`).
- Fallback decisions with the specific unmet condition.

## Components And Boundaries

### `src/newspaper_translator/bloomberg_edition.py`

- `detect_bloomberg_edition(pdf_path) -> bool`
- `find_contents_page(reader) -> int | None`
- `parse_contents_entries(text) -> list[ContentsEntry]` (folio, title, section; wrapped-line
  joining; monotonic/range filtering)
- `detect_page_offset(reader) -> int | None` (vote over `Bloomberg Businessweek <N>`)
- `compute_article_ranges(entries, offset, total_pages) -> list[ArticleRange]`
- `extract_article_text(reader, start, end) -> str` (cleaning)
- `extract_article_images(reader, start, end, images_dir) -> list[str]` (returns relative
  image paths to embed)
- `parse_bloomberg_edition(pdf_path) -> ParsedEdition`
- `BLOOMBERG_EDITION_PARSER_VERSION = "bloomberg-edition-v1"`

### `src/newspaper_translator/document_processing.py`

- Add the `detect_bloomberg_edition` branch to `_build_parse_persist_callback`, between the
  Economist branch and the MinerU branch.

### `src/newspaper_translator/article_pipeline.py`

- Add `persist_bloomberg_edition_articles` (thin wrapper over the Economist persist with the
  Bloomberg parser/name/version), or call the Economist persist with those parameters.

## Data Flow

`Bloomberg PDF → detect_bloomberg_edition (pdf-lib + Contents page + ≥8 entries + offset)
→ parse_bloomberg_edition: find Contents page → parse entries (folios, wrapped titles,
sections) → detect offset (+2) → ranges [folio+offset, next) → per article: clean text +
extract images + embed ![](…) → ParsedEdition → persist_bloomberg_edition_articles →
record_parse_run_result → final_articles + article_images (hero = largest) → enrichment.`

If detection fails at any step → MinerU path (unchanged).

## Testing

### Contents parsing

- Parse the sample Contents lines into entries: correct count, folios `[10…108]`, wrapped
  title `United's CEO … courting influencers` → folio 84, footer lines excluded, sections
  assigned for the known labels.
- Non-decreasing/range filter rejects a footer line ending in a phone number.

### Offset and ranges

- `detect_page_offset` returns `2` for the sample (mode over folio markers).
- `compute_article_ranges`: first article starts at physical `12` (folio 10 + 2), ranges are
  contiguous and sorted, last spans to the final page, pages before the first entry dropped.

### Text and images

- `extract_article_text` strips the running header and `ADVERTISEMENT` lines.
- `extract_article_images` writes files and returns relative paths; embedded `![](…)`
  references are present in the article body and resolve through
  `extract_local_image_paths_and_clean_text`.

### Detection and fallback

- A Bloomberg-shaped sample (pdf-lib + Contents page) → `detect_bloomberg_edition` true.
- A PDF with no Contents page, or fewer than the entry threshold, or no dominant offset →
  false (routes to MinerU). A `pypdf` read error → false.
- A Calibre Economist PDF still routes to the Economist parser (Bloomberg detection false).

### End-to-end smoke (real sample)

- Parse the real Bloomberg sample: ~35 articles (not 141), first article folio 10 → physical
  12, each article has a resolved hero image, `source_name = 彭博商业周刊`,
  `publication_date = 2026-06-01`.

## Acceptance Criteria

- The real Bloomberg sample parses to roughly the Contents-entry count (~35), not ~141.
- Ads and fillers no longer appear as separate article cards.
- Each article card has a hero image drawn from its page range.
- `source_name = 彭博商业周刊` and `publication_date = 2026-06-01`.
- A Bloomberg issue whose Contents cannot be parsed reliably falls back to MinerU rather than
  producing empty or broken output.
- The Economist Calibre path and the existing MinerU path for other publications are
  unaffected.
