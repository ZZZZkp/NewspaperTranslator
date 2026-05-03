# Gmail Body-Link Download Design

Date: 2026-05-03

## Summary

This design updates the Phase 2 Gmail ingestion path to handle recent email-format and link-format changes without changing the rest of the import pipeline.

The scope is intentionally narrow:

- stop using long download URLs as raw-PDF filenames or attachment identifiers
- allow imports from one additional sender: `dengtawaikan@dengtazk.xin`
- support a new body-link family under `https://www.dengtazk.xin:8282/api/public/email-download`
- skip known Chinese translated PDF variants using conservative filename-based rules

The existing Gmail import, import-audit, document creation, deduplication, and downstream processing flow should remain intact.

## Goals

- keep Gmail import working for direct attachments and existing QQ Mail body-link downloads
- prevent path-length failures caused by URLs being embedded in file-oriented identifiers
- add deterministic handling for the new `dengtazk.xin:8282` link type
- preserve enough audit detail to trace each imported body link back to its original message URL
- skip clearly identified Chinese translated PDFs without aggressively filtering unknown files

## Non-Goals

- no broad refactor of the Gmail ingestion architecture
- no browser-automation dependency in the normal import path
- no content-based language detection inside PDF bytes
- no aggressive filtering of suspected translated files beyond explicitly approved patterns

## Current Problem

The current body-link path converts discovered URLs into `GmailAttachment` entries and stores the full URL inside `attachment_id`. That value later participates in raw-PDF storage path generation. With the new long signed links, the generated path can exceed filesystem filename limits and fail before the imported PDF is written.

The new email format also introduces a second download flow:

- some links expose a page with a clear download action
- some links expose a preview page that still loads the full PDF through page scripts or embedded resource URLs

The importer must support both without requiring an interactive browser session.

## Approaches Considered

### Approach 1: Extend the existing body-link pipeline with typed link resolvers

Add a small routing layer inside the current Gmail body-link extraction logic. Existing and new link families are resolved by specialized helper functions, but all successful results still become normal `GmailAttachment` objects and go through the current import path.

Pros:

- minimal change to architecture
- preserves current audit and dedupe behavior
- localized implementation and tests

Cons:

- adds some conditional logic to the current Gmail module

### Approach 2: Introduce a generic resolver registry abstraction

Create a more formal plugin-style registry for body-link resolvers.

Pros:

- cleaner long-term extension point

Cons:

- larger refactor than needed for the current issue
- more moving pieces before behavior is restored

### Approach 3: Use browser automation for preview pages

Drive the preview page in a browser and capture the real PDF network request dynamically.

Pros:

- robust for heavy client-side pages

Cons:

- adds runtime complexity and infrastructure mismatch to a CLI ingestion path
- harder to test and maintain for this repository’s current backend-centric design

## Decision

Use Approach 1.

We will extend the current Gmail body-link pipeline with a small amount of typed resolution logic, keep the import boundary centered on `GmailAttachment`, and avoid architectural churn until a broader ingestion redesign is actually needed.

## Sender Selection

The Gmail config should include the additional allowed sender:

- `dengtawaikan@dengtazk.xin`

No other sender-selection behavior changes.

## Stable Body-Link Identity

Body-link-derived attachments must stop using the full URL as the operational attachment identifier.

Design rules:

- preserve the original source URL in audit records as `link_url`
- generate a short stable identifier for body-link attachments, still prefixed with `link:`
- derive the short stable identifier from a normalized URL string and hash it
- use the stable identifier for import item identity and raw-path generation

Expected effect:

- the importer still distinguishes body-link items from normal attachments
- audit records still show the real URL
- raw file paths remain short and filesystem-safe

This change should apply to both existing QQ Mail link imports and the new `dengtazk.xin:8282` link imports so the storage strategy is consistent across link-based sources.

## Raw PDF Filename Strategy

Imported raw-PDF paths should no longer inherit uncontrolled filename material from signed URLs.

Design rules:

- if the final HTTP response exposes a filename via headers, use that as the preferred filename
- otherwise, if the landing page exposes a clear human-readable filename, use it
- otherwise, generate a fallback filename such as `body-link-<short-hash>.pdf`
- sanitize any chosen filename before path construction
- keep the current content-hash-based uniqueness behavior in the final raw path

The stored document metadata should still record the chosen `original_filename`, since later publication-date inference and operator views already depend on it.

## Link-Type Routing

Body-link resolution should branch by URL family.

### Existing QQ Mail Links

Keep the current `wx.mail.qq.com/ftn/download` handling intact.

The only expected behavior change is that the resulting body-link attachment identity and fallback filename become short and filesystem-safe under the new shared naming rules.

### New `dengtazk.xin:8282` Links

Recognize links under:

- `https://www.dengtazk.xin:8282/api/public/email-download`

Resolver flow:

1. Fetch the URL.
2. If the response is already a PDF, import it directly.
3. If the response is HTML, inspect it for a direct download action first.
4. If no direct action is present, treat it as a preview page and inspect the page structure for the real PDF resource.
5. Fetch the resolved resource URL.
6. Verify that the fetched content is actually a PDF before turning it into a `GmailAttachment`.

## Preview-Page Resolution

Preview pages should be resolved using static response analysis rather than a browser runtime.

The resolver should inspect:

- obvious download anchors and button links
- form actions and hidden inputs that point to a PDF resource
- `iframe`, `embed`, and `object` elements
- inline script assignments
- external script configuration values when the relevant resource URL is embedded in the HTML
- common preview parameters such as `file=...`, `pdfUrl`, `downloadUrl`, `src`, or similar resource-bearing fields

The goal is not to fully execute arbitrary JavaScript. The goal is to recover the concrete PDF resource URL exposed by the page’s static HTML and script configuration.

If the page only exposes an intermediate API endpoint rather than a final PDF URL, the resolver may call that endpoint as long as the result remains part of the same deterministic HTTP-based flow.

## Conservative Chinese-Translation Filtering

The importer should skip clearly identified Chinese translated PDFs after it has determined the candidate filename.

Initial conservative skip patterns:

- filename contains `中文-华尔街日报`
- filename contains `中文-金融时报`
- filename contains `【译】The_Economist_(Web_Edition)_0205.pdf`

Matching strategy:

- evaluate the normalized final filename first
- if needed, allow the same conservative checks against nearby page-exposed file labels or download-button labels
- do not attempt broad Chinese-character rejection
- do not reject files just because the email body contains Chinese text

Skipped translated files should be recorded as skipped body-link items rather than failed imports.

## Error Handling

Add explicit detail codes for the new resolution states where useful, for example:

- `body_link_filename_filtered`
- `dengtazk_download_link_not_found`
- `dengtazk_preview_pdf_not_found`
- `dengtazk_non_pdf_resource`

Behavior:

- unsupported or unresolved preview/download flows should produce failed body-link audit items
- business-rule filtering for translated PDFs should produce skipped body-link audit items
- inability to determine a friendly filename should not fail the import if valid PDF bytes are available

## Testing

Add focused unit tests around the Gmail link-resolution path.

Required coverage:

- body-link imports no longer generate long raw filenames from full URLs
- existing QQ Mail link behavior still resolves successfully
- the new `dengtazk.xin:8282` page with a download button resolves to a PDF attachment
- the new `dengtazk.xin:8282` preview page resolves the underlying PDF resource from static HTML or script data
- translated-PDF filename filtering skips only the explicit approved patterns
- ordinary English filenames continue to import

Regression intent:

- preserve current dedupe behavior
- preserve current import-audit recording shape
- avoid changing direct Gmail attachment imports

## Implementation Notes

The expected implementation center is:

- [src/newspaper_translator/gmail.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/gmail.py)
- [src/newspaper_translator/ingestion.py](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/src/newspaper_translator/ingestion.py)
- [config/gmail-config.json](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/config/gmail-config.json)
- related Gmail and ingestion tests under [tests](/Users/pzk/workspace/NewspaperTranslator/NewspaperTranslator/tests)

The preferred code shape is small helper functions rather than a broader ingestion rewrite.

## Risks and Mitigations

- Risk: preview-page parsing may depend on page-specific HTML or script conventions.
  Mitigation: keep the resolver layered and explicit, and add fixture-style tests for the known page variants.

- Risk: body-link identity changes could affect dedupe behavior.
  Mitigation: continue deriving the final document identity from message id, attachment identity, and content hash, and keep audit-visible source URLs separate from storage-facing identifiers.

- Risk: filename-based filtering may miss some translated variants.
  Mitigation: accept this intentionally as part of the conservative filtering policy and extend only when new confirmed patterns appear.

## Acceptance Criteria

- a Gmail import run no longer fails because a body-link URL is embedded in the raw PDF filename
- messages from `dengtawaikan@dengtazk.xin` are eligible for import
- known `dengtazk.xin:8282` download-button pages can be imported as PDFs
- known `dengtazk.xin:8282` preview pages can be resolved into the underlying PDF resource without browser automation
- explicitly recognized Chinese translated filenames are skipped
- existing QQ Mail body-link imports still work
