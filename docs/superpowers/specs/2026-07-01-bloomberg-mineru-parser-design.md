# Bloomberg Businessweek MinerU-Driven Parser — Design

Date: 2026-07-01
Status: Approved (pending spec review)

## Problem

The current Bloomberg path (`bloomberg_edition.py`) parses locally with pypdf,
deriving article boundaries from the printed Contents page plus a detected
printed→physical page-number offset. It deliberately avoids MinerU (cost /
rate limits). This has three weaknesses proven in this session:

1. **Titles are wrong** — it uses the Contents-page text, which is a teaser, not
   the printed headline.
2. **No real cross-page/column handling** — it slices each article as "start
   folio → next article's start folio", so ads and interleaved content inside a
   range leak in, and multi-column reading order is not reconstructed.
3. **Fragile offset dependency** — folio-offset voting is the segmentation
   backbone.

## Decision

Replace the local Bloomberg parser entirely with a **MinerU-driven** parser.
Every Bloomberg issue is parsed through the MinerU API (whole-document, one
batch — measured 52s / 112 pages for the June 2026 issue). We accept the API
cost / rate-limit exposure in exchange for correct headlines, native
multi-column + contiguous cross-page stitching (via MinerU reading order), and
image extraction.

Segmentation approach (**Approach A**): MinerU `type:title` blocks drive the
boundaries; the printed Contents page acts as an authoritative **whitelist** to
keep only real article titles and reject pull-quotes / chart titles / ad
slogans (which MinerU also tags as `type:title`).

### Evidence base (June 2026 issue, full parse)

- MinerU `content_list.json` blocks carry: `type`, `text_level`, `page_idx`,
  `bbox` ([x0,y0,x1,y1] scaled 0–1000), `text`.
- `type` already separates furniture: `page_number`, `footer`/`page_footer`,
  `header`/`page_header` (running section name), `aside_text`/`page_aside_text`
  (photo/data credits), `image`, `chart`, `text`/`paragraph`, `title`.
- Real headlines: bbox height 33–393px. Chart titles / figure captions: ~14–16px.
- Editorial-page stamp = has a folio (`page_number`) **or** a running section
  header. Ad pages have neither (their folio is absent; their "header", if any,
  is ad copy — e.g. ParkElm "PARK ELM RESIDENCES AT CENTURY PLAZA").
- Some ads carry `header == "ADVERTISEMENT"` (advertorials, e.g. vivo).
- **No true in-column inline ads** in this issue — every ad is a full-page (or
  spread) insert. Ad detection is therefore at **page** granularity.
- Continuation: solid `◀`/`▶` arrows do **not** survive into text (0 found);
  no "continued on page N" text; white `▷` (17) are cross-references to *other*
  articles (Contents / section TOC), not intra-article continuations.
- End-of-article: `<BW>` colophon appears at true article ends but with **low
  recall** (5 captured of ~30 articles; sometimes degrades to `�`). Use only to
  trim trailing contributor credits, never as the primary boundary.

## Architecture

### Data flow

```
PDF ──MinerU.parse_pdf──▶ content_list blocks (type, text_level, page_idx, bbox, text)
                                 │
   ┌─ parse_contents(blocks) ───────────────▶ [ContentsEntry(title, folio)]   (whitelist)
   ├─ classify_pages(blocks) ───────────────▶ {page_idx: PageKind(kind, section)}
   ├─ find_boundaries(blocks, contents, page_kinds) ─▶ [Boundary(title, page_idx, block_index, contents_entry)]
   └─ assemble_articles(blocks, boundaries, page_kinds, images_dir) ─▶ [EditionArticle]
                                 │
                                 ▼
                          ParsedEdition (unchanged downstream)
```

### Module boundaries

New `bloomberg_edition.py` (full rewrite) of small, pure, independently testable
functions:

| Unit | Input → Output | Notes |
|---|---|---|
| `mineru.parse_pdf` (**extend**) | also returns parsed `content_list` blocks | zip already contains `*_content_list.json`; currently discarded |
| `load_blocks(content_list)` | raw list → `list[Block]` dataclass | fields: `type`, `text_level`, `page_idx`, `bbox`, `text` |
| `parse_contents(blocks)` | blocks → `list[ContentsEntry(title, folio)]` | reuses trailing-folio regex idea from current parser |
| `classify_pages(blocks)` | blocks → `{page_idx: PageKind}` | editorial vs ad + section label |
| `find_boundaries(blocks, contents, page_kinds)` | → ordered `[Boundary]` | bbox height filter + fuzzy Contents match + folio fallback |
| `assemble_articles(blocks, boundaries, page_kinds, images_dir)` | → `[EditionArticle]` | body + images + section + end-mark trim |
| `parse_bloomberg_edition(pdf_path, images_dir, mineru_client)` | → `ParsedEdition` | orchestrator |

Output structures (`EditionArticle`, `ParsedEdition`, `build_economist_parse_result`)
are reused unchanged, so persistence and downstream translation are untouched.

### Changes outside the module

- `mineru.py`: `MineruParsedDocument` gains a `content_list` field; `parse_pdf`
  parses `*_content_list.json` from the already-extracted zip.
- `article_pipeline.persist_bloomberg_edition_articles`: gains a `mineru_client`
  parameter, threaded to `parse_bloomberg_edition`.
- `document_processing.py` (~L1900): pass `mineru_client=mineru_client` into the
  Bloomberg persist call (client already in scope).
- `detect_bloomberg_edition`: stays local & cheap (pypdf) — "bloomberg
  businessweek" in first 15 pages + Producer not Calibre + a Contents page
  exists. **Remove** the `detect_page_offset` requirement. No MinerU call to
  detect.

## Algorithms

### `classify_pages` — per page: EDITORIAL / AD + section

Evaluate in order:

1. **Editorial stamp → EDITORIAL** if either:
   - a `page_number` block exists (printed folio), or
   - a `header`/`page_header` block whose text matches a **running section name**
     (collected dynamically from Contents / section openers — not hardcoded).
   - `section` = normalized running-header text.
2. **Ad stamp → AD** if either:
   - a `header` block text == `ADVERTISEMENT` (advertorial), or
   - page is **not** editorial AND contains an ad token: URL
     (`\b[\w-]+\.(com|net|org)\b` inside a short/slogan block), phone
     `\(\d{3}\)\s?\d{3}`, financial legalese (`FINRA|SIPC|Member\s*[-–]\s*NYSE|
     Past performance`), marketing disclaimer (`marketing purposes|informational
     purposes`), `BOOK NOW|Learn more at`.
3. **Fallback**: not editorial + no ad token + no Contents-matching title + low
   body word count → AD (brand full-page ad); else if it has a Contents-matching
   title or a running header → EDITORIAL (legitimate non-folio opener / infographic
   spread).

Trap (observed): an ad's own title bar can be tagged `header` (ParkElm). Step 1
must therefore test **header text ∈ running section names**, not merely "a header
block exists".

### `find_boundaries` — title blocks → real boundaries

Candidates = all `type:title` blocks in reading order. Filter each:

1. Drop small type: bbox height `(y1 - y0) < 22` (chart titles / captions ~14–16;
   real headlines 33–393).
2. Drop titles on AD pages.
3. Fuzzy-match Contents whitelist: normalize (NFKC, lowercase, strip
   punctuation/whitespace); keep if **normalized-substring containment** OR
   **token-set Jaccard ≥ 0.6**. Match → real boundary (record Contents entry,
   `page_idx`, block index). No match → drop (pull-quotes, decorative slogans
   fall out naturally; no separate pull-quote classifier needed).
4. **Folio fallback (Approach C safety net)**: after the pass, for any Contents
   entry with no matched title (MinerU missed the headline), estimate its start
   page via `folio + offset` and insert a boundary at the first editorial text
   block on that page. `offset` is computed by voting over MinerU `page_number`
   blocks (free; not a hard dependency).

### `assemble_articles` — body assembly

For each pair of consecutive real boundaries:

- Take blocks between them in reading order.
- Keep only `type ∈ {text/paragraph, title (subhead/byline), image, chart}` on
  EDITORIAL pages; drop `page_number`/`footer`/`header`/`aside_text` and all
  blocks on AD pages.
- Body text = text blocks concatenated in reading order (contiguous cross-page /
  multi-column handled for free); drop-cap repair (rejoin an isolated leading
  single capital letter to the following word).
- Images = image/chart blocks → written to `images_dir` (reuse existing sha256
  dedupe) → append `![](images/…)` to body.
- `section` = start page's running-header label.
- Tail cleanup: truncate at `<BW>` and drop the trailing contributor credits /
  `—With …` that follow it (present-only; low recall does not affect correctness).

## Error handling

Full replacement, no local fallback — behaves like other MinerU papers:

- MinerU failure / timeout / rate-limit → exception propagates; `parse_run`
  marked failed (reuse existing MinerU failure/retry path).
- Missing or unparseable `content_list.json` → `raise MineruError`.
- Contents page not found / 0 articles produced → `raise ValueError` (matches
  current "Contents not found" behavior).
- **Sanity check (soft warning, non-fatal)**: if extracted article count deviates
  far from Contents entry count (e.g. < 60%), record a warning in `debug_text`
  for human review, but still persist the articles obtained.
- Publication-date resolution unchanged (`resolve_publication_date`).

## Testing (TDD)

Pure functions fed fixed `content_list` JSON fixtures (offline):

- `parse_contents`: entries with multi-line titles and section splits.
- `classify_pages`: editorial (folio), running-header page, ParkElm trap
  (header is ad copy → AD), ADVERTISEMENT advertorial, brand full-page ad,
  non-folio infographic opener (→ EDITORIAL).
- `find_boundaries`: real-title match, chart-title (small bbox) rejection,
  pull-quote (non-match) rejection, missed-title → folio fallback.
- `assemble_articles`: cross-page/column stitch, drop-cap repair, `<BW>` tail
  truncation, ad-block removal, image references.

Fixtures cut from the already-parsed full `content_list.json` (In Context slice +
AI Issue slice + a few ad pages) into `tests/fixtures/`.

Integration (opt-in, needs token, skipped by default): `@pytest.mark.live` real
whole-magazine MinerU parse; assert article count ≈ Contents count and no ad
titles leak in.

## Out of scope (YAGNI)

- Non-contiguous "jump" continuation and solid `◀`/`▶` arrow recovery.
- pdfplumber layout route.
- Page-sliced MinerU for Bloomberg (breaks cross-page reading order; whole-doc
  is used).

## Caveats to validate later

- "Ads always lack a folio" and "no in-column inline ads" are verified on the
  June 2026 issue only. Re-validate across 1–2 more issues (especially
  back-of-book `Pursuits` small-space pages) before treating as an invariant.

## Revision 2 (2026-07-02) — folio-anchored boundaries (real-data correction)

Deploying v1 on the real June 2026 issue produced 14 teaser-titled articles out
of 26. Three root causes (found via systematic debugging on the container):

1. **Wrong heading field.** `find_boundaries` selected `block.type == "title"`,
   but MinerU's `content_list.json` (the file `load_blocks` reads) marks headings
   as `type == "text"` with a `text_level` field — `type == "title"` count is 0.
   (`type:title` exists only in `content_list_v2.json`, which is not read.) So
   zero candidates were found and every boundary came from the folio fallback.
2. **Contents entries are teasers, not headlines.** The printed Contents lists
   descriptions ("Seeking a better way to farm salmon"), not the printed
   headlines ("Salmon Farming, Now on Land"). Headline↔teaser matched 0/26 by
   substring/Jaccard, so Contents cannot serve as a lexical whitelist, and
   emitting `entry.title` produced teaser titles.
3. **Over-aggressive ad classification.** `classify_pages` marks a page `ad` on
   the ABSENCE of folio + running-header. Full-bleed section/feature openers
   (no folio) were mis-marked `ad`, dropping real articles ("The Summer of Our
   Discontent" p16, "A Walk With" p32).

### Corrected approach

Contents gives the reliable **count + start folios**; MinerU `text_level`
headings give the reliable **title text**. Marry them; never lexically match
teaser↔headline. The June 2026 issue has ~26 articles (matches the Contents
count); the AI-issue intro is its own article; listicles (watch roundup, "How
the Boss Uses AI") are one article each with sub-items in the body.

- `parse_contents` → article-start entries keyed by **folio** (dedup; drop
  caption/teaser-only noise lines). Entry titles are no longer emitted as output.
- Build an exact **folio → page_idx map from `page_number` blocks** (no global
  offset — ads make a single offset drift).
- `classify_pages` marks `ad` only on **positive evidence** (an `ADVERTISEMENT`
  header, or an ad-token cluster: URL / phone / FINRA·SIPC / marketing
  disclaimer / "BOOK NOW" / "Learn more at"); default **editorial**. This stops
  folio-less editorial openers from being dropped.
- `find_boundaries`: for each Contents folio `F` → target page via the map →
  search window `[F, F+1, F-1, F+2]` → on the first editorial in-window page
  with a qualifying heading, pick the article headline: the largest/topmost
  `text_level` block with height ≥ ~30, excluding datelines (small height),
  section banners, bylines (`●/○ By`), and pull-quotes (leading quote mark).
  Prefer a heading that has a `●/○ By` byline just below it (booster to beat a
  co-located pull-quote). Join a split second heading line of similar size
  directly beneath. Emit the **heading's text** as `Boundary.title` plus its
  `block_index`.
- `assemble_articles`: **unchanged** — body = editorial text/image blocks between
  consecutive boundaries in reading order; furniture and ad pages dropped.
  Listicle sub-item headings are small and remain in the body, so a roundup
  stays one article.

Byline (`●/○ By`) is a disambiguation **helper**, not the enumerator: ~17
bylines vs ~26 articles, because AI-issue intros, Three Mile Island, Wanna
Merge, and the whole Pursuits section carry no byline.

### Acceptance (against the June 2026 issue)

~24–26 articles with printed headlines (no teasers); no pull-quote / ad /
section-banner titles; editorial openers not dropped. The real issue's
`content_list.json` is the test oracle (hand-crafted fixtures previously hid all
three bugs). Thresholds (height ≥ 30, window +2/−1 pages, split-join size delta
< 25 and gap < 60) are tuned against that fixture.
