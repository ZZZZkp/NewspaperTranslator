# Gmail Body-Link Download Implementation Plan

Date: 2026-05-03

Related documents:

- [Gmail Body-Link Download Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-05-03-gmail-body-link-download-design.md)
- [Gmail Import Audit Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-gmail-import-audit-design.md)
- [Gmail Checkpoint Retry Design](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/docs/superpowers/specs/2026-04-23-gmail-checkpoint-retry-design.md)

## Goal

This plan turns the approved Gmail body-link download design into a staged backend delivery that restores reliable email import under the new mail formats:

- body-link imports stop leaking long signed URLs into raw PDF filenames
- one new allowed sender is accepted
- the new `dengtazk.xin:8282` links work for both download-button and preview-page flows
- clearly identified Chinese translated PDFs are skipped conservatively
- the existing Gmail audit, dedupe, and downstream document-processing flow remain stable

## Execution Status

Status on 2026-05-03: implementation complete. All six slices delivered. CLI verification passed on 2026-05-03.

Summary of outcomes:

- Slice 1 (stable body-link identity): `_body_link_attachment_id` generates `link:body-{hash24}` IDs. Raw paths are now 103 chars, well within filesystem limits. `link_url` remains visible in audit records.
- Slice 2 (sender and translation filtering): `dengtawaikan@dengtazk.xin` added to `allowed_senders` in `config/gmail-config.json`. `www.dengtazk.xin` added to `allowed_link_domains`. `TRANSLATED_FILENAME_PATTERNS` added to `ingestion.py` and used to skip known translated PDFs.
- Slice 3 (dengtazk.xin:8282 resolver): `_is_dengtazk_email_download_url` and `_try_download_direct_pdf` handle direct PDF responses from the new link family.
- Slice 4 (preview-page resolution): `_find_script_resource_url_in_html` extracts PDF URLs from inline script config variables such as `pdfUrl`.
- Slice 5 (audit semantics): translated body-link filenames are now recorded as skipped `body_link` audit items with `detail_code="body_link_filename_filtered"` before the attachment reaches the import pipeline.
- Slice 6 (CLI verification): one real import run on 2026-05-03 fetched 25 messages, created 6 documents, and produced no path-length failures. Two messages failed with `401 Client Error` from dengtazk.xin (time-expired signed URLs, server-side limitation). A new translation filename pattern `【译】` was observed in production but is intentionally outside the initial conservative filter list.

Open items:

- The `【译】华尔街日报` and `【译】金融时报` filename patterns appear in production. They are currently imported. Extend `TRANSLATED_FILENAME_PATTERNS` when the pattern is confirmed as always-translated.
- dengtazk.xin links returning 401 are recorded as `link_fetch_failed`. Slice 5 mentioned adding `dengtazk_download_link_not_found` and related codes; that refinement is deferred until the 401 causes operational confusion.

The repository already has the key foundations for this slice:

- Gmail message listing, filtering, and body-link extraction
- QQ Mail landing-page resolution
- durable import-run and item-level audit history
- raw PDF import into `documents`
- dedupe through stable document identity plus content hash
- retry and checkpoint behavior for repeated Gmail runs

The main gap is that the current body-link path assumes the source URL can safely double as an attachment identity and fallback filename input. That assumption no longer holds for the new long signed links and new preview-style pages.

## Current Starting Point

Current strengths:

- `src/newspaper_translator/gmail.py` already owns Gmail config loading, proxy handling, body parsing, link filtering, and link-to-attachment conversion
- `src/newspaper_translator/ingestion.py` already owns document-key derivation and raw-PDF storage path creation
- current tests already cover direct Gmail attachments, QQ Mail body-link flows, import audit behavior, and dedupe basics

Current limitations:

- body-link attachments still use URL-shaped identifiers
- fallback naming is not explicitly designed for very long signed URLs
- the new `dengtazk.xin:8282` family has no resolver
- translated-PDF filtering rules do not yet exist
- there is no fixture-backed test coverage for preview-style PDF pages

## Delivery Principles

Implementation should follow these principles:

1. Extend before refactor.
   Keep the import boundary centered on `GmailAttachment` and avoid redesigning the ingestion architecture.

2. Separate audit identity from storage identity.
   The original URL should remain visible in audit records, but storage-facing identifiers should be short and stable.

3. Prefer deterministic HTTP resolution over browser execution.
   The normal import path should stay backend-friendly and testable.

4. Keep filters conservative.
   Only skip translated PDFs that clearly match approved filename patterns.

5. Land behavior in independently testable slices.
   Each stage should end with unit tests or CLI-level verification that proves the increment.

## Recommended Delivery Order

### Slice 1: Stabilize Body-Link Identity And Filename Handling

Fix the path-length failure first by separating long source URLs from storage-facing identifiers and filenames.

Scope:

- add a helper that normalizes a body-link URL and derives a short stable hash-based identifier
- stop using full URLs as the operational `attachment_id` for body-link-generated attachments
- keep `link_url` unchanged in import-audit rows
- add or tighten filename sanitization for body-link imports
- prefer response/header-derived filenames when available
- fall back to a generated short filename such as `body-link-<hash>.pdf` when no friendly filename is available

Why first:

- the current import already fails before the new resolver work matters
- this slice lowers immediate filesystem risk for both old and new link families

Likely code areas:

- `src/newspaper_translator/gmail.py`
- `src/newspaper_translator/ingestion.py`
- `tests/test_gmail.py`
- `tests/test_ingestion.py`

Exit criteria:

- body-link imports no longer embed the full URL in raw-storage filenames
- import-item identity for body links remains deterministic
- existing QQ Mail body-link tests still pass under the new identity scheme

### Slice 2: Add Sender And Conservative Translation Filtering

Add the new sender and the explicit translated-PDF skip rules before deepening new link parsing.

Scope:

- update the Gmail config fixture and runtime config to accept `dengtawaikan@dengtazk.xin`
- add a focused helper that recognizes approved translated-PDF filename patterns
- apply the filter after the candidate filename is known but before import proceeds
- record translated matches as skipped body-link items rather than failed items

Why second:

- sender and filtering rules are simple, self-contained business logic
- this keeps later resolver tests focused on true download behavior instead of mixed policy questions

Likely code areas:

- `config/gmail-config.json`
- `src/newspaper_translator/gmail.py`
- `tests/test_gmail.py`
- possibly `tests/test_manage.py` if config expectations are asserted there

Exit criteria:

- the new sender is eligible for selection
- explicit Chinese translated filenames are skipped
- normal English filenames still import

### Slice 3: Introduce Typed Body-Link Resolution For `dengtazk.xin:8282`

Add the new link-family resolver while keeping the current QQ Mail flow intact.

Scope:

- recognize `https://www.dengtazk.xin:8282/api/public/email-download` as a dedicated body-link family
- add a resolver path that:
  - fetches the source URL
  - detects direct-PDF responses
  - detects HTML download pages
  - returns a resolved PDF attachment when possible
- keep the resolution result expressed as a normal `GmailAttachment`

Why third:

- with identity and filtering stabilized, the new resolver can focus on link semantics rather than storage fallout
- this slice creates the main extension seam for the new mail format

Likely code areas:

- `src/newspaper_translator/gmail.py`
- `tests/test_gmail.py`

Exit criteria:

- a known `dengtazk.xin:8282` direct-download page resolves into a PDF attachment
- existing QQ Mail resolution remains unchanged in behavior

### Slice 4: Add Preview-Page Static HTML And Script Resolution

Support the new preview-only variant without introducing browser automation.

Scope:

- inspect preview pages for:
  - direct download anchors
  - forms and hidden inputs
  - iframe/embed/object resource URLs
  - inline script assignments and static config variables
  - common fields such as `file`, `pdfUrl`, `downloadUrl`, or similar
- if needed, follow one deterministic intermediate API or resource URL discovered from the page
- confirm the final fetched resource is actually a PDF
- add explicit failure detail codes when the preview path cannot be resolved

Why fourth:

- preview parsing is the highest-uncertainty part of the feature
- it is easier to land after the simpler direct-download path proves out the new resolver structure

Likely code areas:

- `src/newspaper_translator/gmail.py`
- `tests/test_gmail.py`

Exit criteria:

- a known preview-style page can be resolved into the underlying PDF resource
- unresolved preview pages fail with clear audit detail codes rather than ambiguous generic failures

### Slice 5: Tighten Audit Semantics And Failure Reporting

Make the new flows observable and easy to debug from the existing audit surfaces.

Scope:

- add or refine detail codes for:
  - translated-file skip
  - missing download link
  - preview PDF not found
  - resolved non-PDF resource
- ensure body-link item keys remain stable under the new identity scheme
- verify import-run item records still contain enough information to trace the original source URL and outcome

Why fifth:

- once new resolver behavior lands, clear audit semantics are what make production debugging manageable
- this keeps operator visibility aligned with the repository’s existing import-run tooling

Likely code areas:

- `src/newspaper_translator/gmail.py`
- `src/newspaper_translator/import_audit.py` only if existing helpers need shape adjustments
- `tests/test_gmail.py`
- `tests/test_web.py` or `tests/test_manage.py` if audit outputs are asserted there

Exit criteria:

- new skip and failure states are explicitly visible in audit items
- item keys and URLs remain traceable after the identity change

### Slice 6: Run Targeted CLI Verification Against Real Mail Inputs

Validate the behavior end to end in the existing local verification environment after unit coverage passes.

Scope:

- rerun `gmail-import` using the project virtual environment
- use the local proxy-compatible environment values that work on the host
- verify at least:
  - long signed URLs no longer cause filename/path overflow
  - new sender mail is selectable
  - translated PDFs are skipped when they match approved patterns
  - at least one known `dengtazk.xin:8282` page downloads successfully
- if preview-page support depends on page-specific structure, capture the final observed pattern in tests before closing the slice

Why sixth:

- unit tests should lead the implementation, but this feature ultimately exists to survive real email input
- the last known failure already came from real-world URL length, so end-to-end verification is essential

Exit criteria:

- one real import run completes without the previous path-length failure
- the observed new-page variants are covered by both runtime verification and tests

## Test Strategy

Testing should stay concentrated and incremental.

Core test layers:

- `tests/test_gmail.py`
  - body-link identifier shortening
  - translated-PDF filtering
  - direct-download page resolution
  - preview-page static parsing
  - new failure detail codes
- `tests/test_ingestion.py`
  - raw-path generation remains short and filesystem-safe
  - imported document metadata still records a usable `original_filename`
- `tests/test_manage.py` and `tests/test_web.py` only where new config or audit-visible behavior is surfaced

Suggested execution order:

1. add or update unit tests for body-link identity and filename handling
2. add sender and translation-filter tests
3. add direct-download resolver tests
4. add preview-page resolver tests
5. rerun the focused Gmail and ingestion suites
6. run one real `gmail-import` verification pass

## Risks And Mitigations

- Risk: preview-page parsing depends on brittle page-specific JavaScript structure.
  Mitigation: implement layered static parsing, cover the observed shapes with fixtures, and emit explicit failure detail codes when the pattern is unknown.

- Risk: changing body-link identifiers could accidentally perturb dedupe or audit-key expectations.
  Mitigation: limit the identity change to body-link attachment ids, keep `link_url` explicit in audit, and preserve document identity derivation semantics.

- Risk: conservative translation filtering may miss some translated variants.
  Mitigation: accept this intentionally, keep the helper small, and extend only when new confirmed filename patterns appear.

- Risk: direct-download and preview flows may expose filenames differently.
  Mitigation: centralize candidate filename selection with a clear precedence order and a stable generated fallback.

## Definition Of Done

This milestone is complete when all of the following are true:

- body-link imports no longer fail because a full signed URL is embedded in a filesystem path
- `dengtawaikan@dengtazk.xin` is accepted by the configured Gmail import flow
- the new `dengtazk.xin:8282` direct-download page variant imports successfully
- the new `dengtazk.xin:8282` preview-page variant resolves to the underlying PDF resource through static parsing
- approved translated-PDF filename patterns are skipped conservatively
- existing QQ Mail body-link imports still work
- focused tests and one real import verification pass both succeed
