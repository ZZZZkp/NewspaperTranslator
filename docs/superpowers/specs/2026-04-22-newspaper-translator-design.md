# Newspaper Translator Design

Date: 2026-04-22

## Overview

This project automatically ingests newspaper PDFs from Gmail, reconstructs article-level content from mixed digital and scanned newspaper layouts, enriches each article with tags, a Chinese summary, and a full Chinese translation, then presents the results in a local dashboard optimized for daily browsing.

The system is designed for:

- Fully automated daily processing
- A local dashboard with waterfall-style news cards
- Mixed PDF inputs, including digital PDFs and scanned PDFs
- Resumable background processing with retries and detailed logs
- Docker-based deployment for easy migration to other machines later
- Cloud model APIs in the first version, with clear boundaries for later replacement

## Goals

- Pull target newspaper PDFs from Gmail automatically through the Gmail API
- Parse newspaper PDFs into article-level objects instead of page-level raw text
- Handle both digital PDFs and scanned PDFs within one unified pipeline
- Generate 3 to 8 AI tags for every article
- Generate a Chinese summary for every article
- Generate a full Chinese translation for every article
- Store both the original English content and the Chinese output
- Provide a local dashboard with source filters, date filters, focused-tag sections, and article detail pages
- Support interruption, restart, retry, and partial completion without losing progress

## Non-Goals For V1

- Perfect layout reconstruction for every newspaper format
- 100 percent accurate cross-page and cross-column reconstruction
- Near-zero ad misclassification
- Advanced editorial tooling for manual correction
- Powerful full-text search, collections, or annotation workflows
- Local-model inference in the first version

## User Experience

### Home Page

The home page is a structured reading surface rather than an algorithmic recommendation feed.

It contains:

- Source filter
- Date filter
- Optional tag filter
- A focused section containing recent articles matching user-selected tags
- A waterfall-style card grid containing all articles

Each article card displays:

- Newspaper image if available
- Chinese summary
- AI-generated tags
- Source and date metadata

Articles without images should not reserve image space.

### Article Detail Page

The detail page is article-centric, not PDF-page-centric.

It contains:

- English title
- Source and page metadata
- AI tags
- Chinese summary
- Optional lead image
- English original text
- Chinese full translation
- Lightweight parsing confidence or quality indicators when needed

The default reading mode is single-language switching. A side-by-side bilingual comparison mode can be offered as an optional expanded view, but it is not the primary interaction.

## High-Level Architecture

The system is split into six modules with durable boundaries.

### 1. Ingestion

Responsibilities:

- Authenticate with Gmail API using OAuth
- Poll or backfill target inbox messages
- Filter messages by sender, date, and attachment type
- Save PDF attachments
- Create one document record per attachment
- Prevent duplicate imports

Design notes:

- The ingestion layer should be idempotent
- Raw email identifiers and attachment identifiers must be recorded
- Original PDFs must always be preserved

### 2. Orchestrator

Responsibilities:

- Drive the end-to-end processing workflow
- Split work into document-level, page-level, and article-level tasks
- Record task status, retries, and failure details
- Resume unfinished work after restart

Design notes:

- Every processing step should be independently retryable
- Running tasks without a recent heartbeat should be recovered after restart
- Already completed outputs should be reused instead of recomputed

### 3. Parser Pipeline

Responsibilities:

- Classify documents and pages
- Extract structured page blocks
- Understand newspaper layout
- Reconstruct article-level content

The parser pipeline is the core of the system.

### 4. AI Enrichment

Responsibilities:

- Generate 3 to 8 tags per article
- Generate a Chinese summary
- Generate a full Chinese translation
- Optionally compute extra display metadata for the dashboard

Design notes:

- Tagging, summarization, and translation should be separate sub-steps
- AI calls should operate on article objects, not raw pages
- Cloud model APIs are used in V1, but the interface should make future replacement easy

### 5. Storage And Index

Responsibilities:

- Store raw inputs
- Store intermediate parsing outputs
- Store article-level final outputs
- Support dashboard queries efficiently

### 6. Local Dashboard

Responsibilities:

- Display article cards and filters
- Show the focused tag area
- Render article detail views
- Surface lightweight processing status information

The dashboard should read processed content from storage and should not trigger heavy parsing or AI work during browsing.

## Parsing Strategy

The chosen parsing strategy is:

Digital and scanned inputs are both supported, but they converge into one common article-reconstruction pipeline.

The guiding principle is:

Use geometry, OCR, and deterministic rules for structure. Use AI only for ambiguous decisions.

### Why Direct Text Extraction Is Not Enough

Many digital newspaper PDFs contain selectable text, but the text order is often unsuitable for reading because:

- Text objects may be stored in drawing order rather than reading order
- Multi-column layouts break naive extraction
- One article may span several columns
- One article may continue on later pages
- Ads and non-article material interrupt text flow

Because of this, the parsing problem is not just text extraction. It is layout understanding plus article reconstruction.

### Entry Classification

Each document or page should be classified as one of:

- Digital
- Scanned
- Mixed

Heuristics include:

- Presence and density of extractable text
- Whether the page is mostly a large raster image
- Whether extracted text is abnormally sparse or structurally broken

### Digital Path

For digital pages:

- Extract text blocks, characters, font signals, images, and coordinates
- Detect columns
- Detect title candidates, body candidates, image regions, headers, footers, and ad candidates
- Produce normalized block objects

### Scanned Path

For scanned pages:

- Render page images at high enough resolution
- Perform image preprocessing when needed
- Run OCR to get text and coordinates
- Detect title candidates, body candidates, image regions, headers, footers, and ad candidates
- Produce normalized block objects with confidence scores

### Unified Block Model

Both the digital path and the scanned path must output the same logical block structure.

Each block should include:

- Page reference
- Bounding box
- Block type candidate
- Text
- Extraction source
- Confidence
- Ordering metadata
- Optional image reference

This keeps downstream logic independent from how the text was obtained.

### Layout Understanding

The layout stage performs:

- Column detection
- Reading order estimation inside columns
- Title and lead detection
- Header and footer filtering
- Image caption detection
- Advertisement candidate detection

The first pass should rely on geometry and rules. It should not depend on a large model to understand every page.

### Ambiguity Resolution

AI should only be used for difficult decisions such as:

- Whether two nearby text groups belong to the same article
- Whether a large region is an ad or a news article
- Whether a continuation block belongs to an earlier article
- Whether a candidate block is truly a title or just a large-format sidebar

This is the selected approach because it balances cost, control, explainability, and future model replacement better than either a purely rule-based system or a purely multimodal end-to-end system.

### Article Reconstruction

The system should reconstruct article objects by:

- Detecting article starts from title candidates
- Grouping title, lead, body, and related image blocks
- Following same-column and same-page continuation candidates
- Resolving cross-column and cross-page continuation
- Marking low-confidence or incomplete articles explicitly

The output of parsing is an article object, not a raw page transcript.

## Processing Workflow

The high-level workflow is:

`Gmail -> Raw PDF -> Page Classification -> Page Blocks -> Article Reconstruction -> Tags -> Summary -> Translation -> Dashboard`

### Document-Level Tasks

- Pull target email
- Save attachment
- Create document record
- Trigger downstream processing

### Page-Level Tasks

- Classify page type
- Extract text or run OCR
- Build block candidates
- Run layout analysis
- Record page quality indicators

### Article-Level Tasks

- Reconstruct article
- Generate tags
- Generate summary
- Generate translation
- Update display indexes

This task granularity allows partial completion. For example:

- If one page fails OCR, the rest of the document can still be processed
- If one article fails translation, the document can still appear in the dashboard

## State, Retry, And Recovery Design

The system must be robust to machine sleep, shutdown, Docker restart, and transient API failures.

### Task States

Each task records:

- `pending`
- `running`
- `retrying`
- `succeeded`
- `failed`
- `partial`

Additional fields should include:

- Attempt count
- Last error
- Start time
- Finish time
- Worker identifier
- Input hash
- Output reference
- Last heartbeat time

### Retry Policy

Three retry classes are recommended.

#### 1. Automatic Retry For Transient Failures

Examples:

- Gmail API timeouts
- Cloud model API timeouts
- Temporary OCR service failures

These should use bounded exponential backoff.

#### 2. Structured Failure For Persistent Problems

Examples:

- Damaged PDF
- Page extraction returns almost nothing
- OCR confidence is too low
- Reconstructed article is suspiciously incomplete

These should not loop forever. They should move into `failed` or `partial` with a clear reason.

#### 3. Safe Re-Run

Any processing step should be re-runnable without corrupting data or duplicating work.

Examples:

- Existing PDFs are not imported twice
- Completed pages are not reparsed unless inputs change
- Completed AI outputs are reused unless their inputs change

### Recovery

On restart, the orchestrator should:

- Scan for unfinished documents
- Detect stale running tasks with missing heartbeats
- Requeue safe retries
- Reuse completed artifacts
- Update final document status to `succeeded` or `partial`

### Logging

Logs should exist at three levels:

#### System Logs

- Worker startup and shutdown
- Queue activity
- Container-level failures

#### Task Logs

- Page classified as digital or scanned
- OCR confidence
- Number of title candidates
- Cross-page continuation detected
- Translation failed and scheduled for retry

#### User-Visible Events

These should be visible in the dashboard, for example:

- Three new documents imported today
- One document is still processing
- Two articles have low parsing confidence
- One translation is being retried

## Data Model

The data model should center on article objects.

### `source`

Represents a newspaper source.

Suggested fields:

- Name
- Sender matching rule
- Default parsing strategy configuration
- Enabled flag

### `document`

Represents one imported PDF attachment.

Suggested fields:

- Source reference
- Gmail message id
- Attachment id
- File path
- Newspaper date
- Page count
- Processing status
- Input hash

### `page`

Represents one page within a document.

Suggested fields:

- Document reference
- Page number
- Page type
- Rendered image path
- Parsing status
- Quality score

### `block`

Represents one structured page block.

Suggested fields:

- Page reference
- Bounding box
- Type candidate
- Text
- Extraction source
- Confidence
- Reading order metadata

### `article`

Represents one reconstructed article and is the main domain entity.

Suggested fields:

- Source reference
- Document reference
- English title
- English body
- Chinese summary
- Chinese full translation
- Lead image path
- Start and end pages
- Parsing confidence
- Incomplete flag
- Published date
- Display status

### `article_tag`

Represents tags assigned to an article.

Suggested fields:

- Article reference
- Tag text
- Confidence
- Rank

### `user_tag_preference`

Represents the set of tags the user wants highlighted on the home page.

Suggested fields:

- Tag text
- Focused flag
- Sort weight
- Hidden flag

## Dashboard Query Model

The dashboard needs fast support for:

- Articles by date range
- Articles by source
- Articles matching selected tags
- Articles matching focused tags

Indexes should prioritize:

- Article published date
- Article source
- Tag text
- User tag preferences

Processed summaries, tags, and translations should be stored, not generated during browsing.

## Home Page Organization

The home page has three main layers.

### Top Filter Area

Contains:

- Source filter
- Date filter
- Optional tag filter
- Optional visibility filter for processing quality

### Focused Tag Section

This section contains recent articles matching tags the user explicitly selected.

Rules:

- It is article-based, not tag-entry-based
- One article appearing under multiple focused tags is shown once
- It should prioritize recency and relevance

### All Articles Waterfall Grid

This section contains all articles, even those already shown in the focused area.

Cards should display:

- Optional image
- Chinese summary
- Tags
- Source and date

If an article already appears in the focused section, the card may contain a light indicator, but it should not feel duplicated or noisy.

## Detail Page Organization

The detail page should prioritize reading comfort and article context.

Suggested structure:

- Title
- Source and page metadata
- Tags
- Chinese summary
- Optional lead image
- Main reading area with language switching
- Optional parsing-quality hint
- Optional access to original page images

The original PDF page view is secondary. It is useful for verification and debugging, but it should not be the primary reading surface.

## Deployment

The first version should be packaged with Docker.

Recommended `docker compose` services:

- `worker` for ingestion, parsing, and AI jobs
- `web` for the local dashboard and API
- `db` for metadata and content storage
- Optional `queue` service if asynchronous coordination needs stronger isolation

This structure fits the current requirement of always-on local execution while making later migration easier.

## Testing Strategy

Testing should focus on usefulness and stability rather than perfection.

### 1. Parsing Tests

Verify:

- Digital PDFs produce stable structured blocks
- Scanned PDFs produce normalized blocks through OCR
- Ads, headers, and footers do not dominate reconstructed article text
- Common cross-column and cross-page cases are handled reasonably well

The initial test corpus should include:

- Two digital newspaper PDFs
- Two scanned newspaper PDFs
- At least one cross-page article
- At least one page with strong ad interference

### 2. Task And Recovery Tests

Verify:

- Docker restart resumes work
- Machine sleep and wake do not leave tasks permanently stuck
- API and OCR failures retry correctly
- Duplicate email ingestion is prevented
- Finished work is reused instead of recomputed

### 3. Content Quality Tests

Verify:

- Every article receives 3 to 8 tags
- Summaries are stable and appropriate for cards
- Chinese translations are complete enough to read as full articles
- Focused-tag grouping behaves as expected
- Low-confidence articles are marked appropriately

Initial quality review should include a small amount of human spot checking.

### 4. Dashboard Experience Tests

Verify:

- Source and date filters work
- Focused-tag and all-articles sections behave consistently
- Cards render properly with and without images
- Language switching works on detail pages
- Metadata hierarchy is readable and uncluttered

## V1 Acceptance Criteria

Version 1 is considered successful when all of the following are true:

1. The system automatically imports target Gmail PDFs without duplicating them.
2. The system reconstructs most news content into article-level objects for common digital and scanned newspaper inputs.
3. Every article can produce English content, a Chinese summary, a Chinese full translation, and 3 to 8 tags.
4. The local dashboard supports waterfall browsing, source filtering, date filtering, focused-tag sections, and article detail pages with language switching.
5. The system can resume after interruption and continue processing without routinely starting over.
6. Logs and status indicators make it obvious what has been imported, what is still processing, and what failed or has low confidence.

## Future Expansion

The following are intentionally deferred but supported by the architecture:

- Replacing cloud AI APIs with local models
- Better newspaper-specific layout adapters
- Manual correction tools
- More powerful search and saved views
- Better PDF image extraction and previewing
- Additional downstream exports or notifications

## Chosen Direction Summary

The selected V1 design is:

- Gmail API plus OAuth for ingestion
- Dockerized local deployment
- Mixed digital and scanned PDF support
- Unified block model across extraction paths
- Rule-based structure parsing with AI only for ambiguous layout decisions
- Article-level enrichment with tags, Chinese summaries, and full Chinese translations
- Local dashboard with focused tags, waterfall cards, and bilingual detail pages

This design emphasizes reliability, explainability, and replaceable components over end-to-end black-box processing.
