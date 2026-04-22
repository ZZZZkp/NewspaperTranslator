# Newspaper Translator Implementation Plan

Date: 2026-04-22

Related spec:

- [Newspaper Translator Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-22-newspaper-translator-design.md)

## Planning Goals

This implementation plan translates the approved design into a staged build sequence that keeps risk under control.

The main planning priorities are:

- Build a working vertical slice early
- Keep parsing, AI enrichment, and dashboard boundaries clean
- De-risk newspaper layout reconstruction before polishing the UI
- Preserve resumability and observability from the start
- Avoid locking the project to one model provider or one deployment target

## Delivery Strategy

The project should be built in seven phases.

The recommended order is:

1. Project foundation and local runtime
2. Gmail ingestion and raw document storage
3. Parsing pipeline v1 with digital-first support
4. Scanned-page support and ambiguity-resolution layer
5. Article enrichment pipeline
6. Local dashboard
7. Hardening, recovery validation, and launch checklist

This order is deliberate.

We should not start from the dashboard because the hardest uncertainty is article reconstruction, not front-end rendering. We also should not try to solve scanned PDFs before the digital path and orchestration are stable. The fastest reliable path is to get a narrow end-to-end slice working on one digital newspaper first, then widen capability step by step.

## Phase 1: Project Foundation And Local Runtime

### Objectives

- Create the initial application skeleton
- Establish local Docker-based development workflow
- Define package, service, and configuration boundaries
- Set up a minimal database schema and migration flow
- Set up structured logging, environment loading, and shared configuration

### Scope

- Choose the main backend language and framework
- Create initial service layout for `worker`, `web`, and `db`
- Add Dockerfiles and `docker compose`
- Add environment variable strategy for Gmail, model API, storage, and database config
- Add migration tooling
- Add logging and shared settings module
- Add base README for local startup

### Suggested Deliverables

- `docker-compose.yml`
- Backend service skeleton
- Web service skeleton
- Database migration baseline
- `.env.example`
- Basic health endpoints or startup checks

### Exit Criteria

- The repo boots locally with Docker
- The app can connect to the database
- Configuration loads cleanly in containers
- Logs are visible and structured

### Risks To Watch

- Choosing a stack that makes OCR and PDF handling awkward later
- Letting configuration sprawl across services

## Phase 2: Gmail Ingestion And Raw Document Storage

### Objectives

- Connect to Gmail through OAuth
- Fetch target emails and PDF attachments
- Save raw attachments safely
- Prevent duplicate imports

### Scope

- Gmail OAuth flow for local use
- Sender and attachment filters
- Document import job
- Raw PDF file storage layout
- Document metadata persistence
- Duplicate detection using message id, attachment id, and content hash
- Initial ingestion logs and status views

### Suggested Deliverables

- Gmail credentials setup instructions
- Ingestion worker module
- Raw storage directory convention
- `source` and `document` tables
- First successful import of a real sample PDF

### Exit Criteria

- The system imports target PDFs from Gmail automatically
- Re-running ingestion does not duplicate documents
- Raw PDFs and metadata can be traced back to the original email

### Risks To Watch

- Gmail token refresh edge cases
- Accidental coupling between ingestion and downstream parsing

## Phase 3: Parsing Pipeline V1 With Digital-First Support

### Objectives

- Build the first article reconstruction path for digital PDFs
- Introduce page and block abstractions
- Prove that newspaper articles can be reconstructed beyond naive text extraction

### Scope

- PDF rendering and text extraction module
- `page` and `block` models
- Page classification heuristics
- Digital block normalization
- Column detection
- Title, body, image, caption, header, footer, and ad candidate detection
- Page-level debug artifacts
- Article reconstruction for same-page and basic cross-page cases

### Suggested Deliverables

- PDF parsing adapter
- Block extraction output format
- Layout analysis module
- Article reconstruction module
- Debug JSON or image overlays for inspected pages
- Small corpus of digital sample PDFs checked into a test fixture strategy

### Exit Criteria

- At least one target digital newspaper can be parsed into useful article objects
- Article outputs are visibly better than naive page text dumps
- Headers, footers, and large ad regions are usually filtered well enough for downstream AI

### Risks To Watch

- Overfitting heuristics to one newspaper too early
- Skipping debug artifact generation and losing visibility into parsing failures

## Phase 4: Scanned-Page Support And Ambiguity Resolution

### Objectives

- Support scanned pages without breaking the digital path
- Add OCR and unify downstream processing
- Introduce limited AI-based ambiguity resolution where rules are insufficient

### Scope

- OCR engine integration
- Image preprocessing hooks
- Unified block model across digital and scanned paths
- Scanned-page confidence scoring
- AI prompts for ambiguous grouping and ad-or-article decisions
- Cross-page continuation improvement for mixed-quality pages
- Partial and low-confidence marking

### Suggested Deliverables

- OCR adapter
- Scanned-page preprocessing module
- Shared block schema
- Ambiguity-resolution service interface
- Confidence and quality annotation fields on pages and articles

### Exit Criteria

- A scanned sample document can reach article reconstruction end to end
- Low-confidence output is explicitly marked instead of silently treated as high quality
- The digital path still works unchanged through the same article pipeline

### Risks To Watch

- Letting the multimodal or LLM layer take over too much of the layout problem
- Missing cost controls on ambiguity-resolution calls

## Phase 5: Article Enrichment Pipeline

### Objectives

- Produce stable tags, summaries, and full Chinese translations
- Keep enrichment steps independent and cacheable
- Prepare the data shape required by the dashboard

### Scope

- Article-level prompt contracts
- Separate tagging, summarization, and translation jobs
- Input hashing for cache-safe reruns
- `article`, `article_tag`, and enrichment status fields
- Output validation rules
- Failure handling for partial enrichment

### Suggested Deliverables

- Enrichment service interface
- Prompt templates and provider adapters
- Output validators
- Persistence for summaries, translations, and tags

### Exit Criteria

- Each reconstructed article can produce 3 to 8 tags
- Chinese summaries are card-ready
- Full translations are saved and viewable
- Failed enrichment for one article does not block the rest of the document

### Risks To Watch

- Combining all enrichment into one giant prompt and losing retry control
- Under-validating malformed model output

## Phase 6: Local Dashboard

### Objectives

- Deliver the user-facing browsing experience
- Surface processed results without triggering heavy background work
- Make focused-tag browsing practical

### Scope

- API endpoints or server-rendered queries for articles
- Home page with source and date filters
- Focused-tag section logic
- Waterfall article grid
- Detail page with language switching
- Optional original-page preview area
- User tag preference management
- Lightweight processing-status surfacing

### Suggested Deliverables

- Dashboard routes and data APIs
- Home page implementation
- Detail page implementation
- Tag preference controls
- Basic styling and responsive behavior

### Exit Criteria

- The dashboard displays imported and enriched articles correctly
- Filters work for source and date
- Focused-tag grouping works without duplicating articles incorrectly
- Detail pages support English and Chinese viewing cleanly

### Risks To Watch

- Pulling parsing concerns into the web layer
- Overbuilding UI before the data is trustworthy

## Phase 7: Hardening, Recovery Validation, And Launch Checklist

### Objectives

- Make the system survivable in everyday use
- Validate restart, retry, and observability behavior
- Lock in V1 acceptance

### Scope

- Retry policy implementation review
- Heartbeat and stale-task recovery
- Sleep, restart, and Docker-recreate validation
- Log review and dashboard status review
- Fixture-based regression tests for parsing and enrichment outputs
- Launch checklist for credentials, storage paths, and scheduled execution

### Suggested Deliverables

- Recovery test checklist
- Regression fixtures for representative PDFs
- Operational notes for local always-on use
- V1 readiness checklist

### Exit Criteria

- Restart and recovery behavior works in realistic local scenarios
- Known failures are visible and understandable
- The system satisfies the approved V1 acceptance criteria in the design spec

### Risks To Watch

- Treating hardening as optional polish instead of a core requirement
- Lacking representative sample documents for regression validation

## Cross-Cutting Workstreams

These workstreams should progress alongside the main phases rather than being postponed entirely.

### Configuration And Secrets

- Standardize environment loading early
- Keep Gmail and model credentials outside the repo
- Document local setup clearly

### Data And Artifact Storage

- Separate raw inputs, intermediate artifacts, and final outputs
- Choose stable storage paths early so later migrations are easier
- Decide what intermediate artifacts are retained for debugging

### Observability

- Use structured logs from the beginning
- Attach document, page, and article identifiers to log lines
- Record enough metadata to explain why parsing or enrichment failed

### Cost Control

- Log model calls and token-heavy ambiguity-resolution steps
- Avoid unnecessary recomputation through input hashes
- Keep AI intervention targeted to article-level semantics and ambiguous layout decisions

### Test Corpus Management

- Build a representative private sample set early
- Include digital, scanned, cross-page, and ad-heavy examples
- Track expected outputs at the article level where possible

## Implementation Order Inside Each Phase

Within each phase, use a vertical-slice approach:

1. Add the data model and storage surface for the new capability.
2. Add the service or worker logic.
3. Add a minimal API or debug surface to inspect outputs.
4. Add fixture-based tests.
5. Validate with one real sample before broadening scope.

This is especially important for parsing work. It is better to have one newspaper partially supported with strong visibility than five newspapers that fail opaquely.

## Suggested Initial Milestones

The first three milestones should be:

### Milestone 1: Repo Can Boot And Import PDFs

Success means:

- Docker services start
- Database migrations run
- Gmail OAuth works
- Real PDFs are saved locally
- Documents are persisted without duplication

### Milestone 2: One Digital Newspaper Reconstructs Into Articles

Success means:

- Digital pages produce structured blocks
- Article reconstruction works for a small real sample
- Results are inspectable with debug artifacts

### Milestone 3: Articles Reach The Dashboard With Chinese Output

Success means:

- Tags, summary, and translation are generated
- The home page shows cards
- The detail page switches between languages

After these three milestones, broaden to scanned pages and hardening rather than expanding UI scope first.

## Recommended Task Breakdown For The First Build Sprint

If implementation starts immediately, the first sprint should focus on the minimum vertical slice:

1. Create project skeleton, Docker setup, environment loading, and database baseline.
2. Implement Gmail ingestion and raw PDF storage.
3. Implement digital PDF block extraction and basic article reconstruction.
4. Persist article objects.
5. Add one enrichment path for summary, translation, and tags.
6. Add a minimal dashboard that lists articles and opens a detail page.

This first sprint does not need:

- Scanned-page support
- Advanced ambiguity resolution
- Final visual polish
- Sophisticated tag management

The goal is to prove end-to-end viability as quickly as possible.

## Dependencies And Decision Points

The following decisions should be made during implementation, not postponed indefinitely:

- Backend framework and language choice
- Database choice
- OCR engine choice
- PDF extraction library choice
- Queue and worker strategy
- Front-end stack choice
- Model provider abstraction boundary

These choices should be evaluated against the approved design, but they do not need to block plan approval as long as the architecture remains modular.

## Done Definition For The Plan

This plan is complete when:

- Work can start phase by phase without re-deciding scope
- Each phase has explicit exit criteria
- The first sprint is small enough to execute
- The design's V1 acceptance criteria remain intact

## Plan Summary

Build the system as a staged vertical slice, starting with Dockerized foundations, Gmail ingestion, and digital article reconstruction. Once the core path works, add scanned-page support, article enrichment, the local dashboard, and finally resilience and recovery hardening.

The most important principle is to center the project on article-level objects with strong intermediate visibility. That is what makes the parsing problem debuggable, the AI outputs replaceable, and the dashboard useful.
