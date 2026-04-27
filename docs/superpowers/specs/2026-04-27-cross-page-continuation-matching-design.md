# Cross-Page Continuation Matching Design

Date: 2026-04-27

## Overview

This document defines the next Phase 3 parsing slice for cross-page newspaper article reconstruction.

The current repository already reconstructs article-like objects from MinerU `full.md` output, but it does not yet merge front-page fragments such as:

- `Please turn to page A7`
- `Please turn to page A9`
- `Continued from PageOne`
- `Continued from pageR1`

The new slice should keep the parser simple and robust:

- collect fragments that contain explicit continuation markers
- ask an LLM only to match continuation fragments with each other
- keep the actual article merge logic in deterministic repository code

This design intentionally does not depend on MinerU reliably extracting the printed newspaper page label such as `A7` or `R2`.

## Goals

- Detect explicit cross-page continuation markers in MinerU Markdown output
- Preserve continuation marker data on parsed article fragments
- Collect only continuation-bearing fragments for LLM matching
- Merge matched fragments into single article outputs
- Clean up marker text and nearby word-gluing noise at the fragment boundary

## Non-Goals

- Guess cross-page relationships for fragments that contain no explicit continuation markers
- Depend on MinerU to reliably recover the current printed page label
- Ask the LLM for summaries, explanations, confidence scores, or editorial cleanup
- Perform general OCR cleanup across the entire document
- Rework the whole parser around physical PDF page splitting in this slice

## Why This Approach

Recent MinerU experiments show that single-page parsing improves visibility into continuation phrases such as `Continued from PageOne`, but it still does not reliably expose the current printed page label. That makes a page-label-driven merge strategy too brittle as the primary path.

The repository already sees enough explicit continuation phrases to identify likely front-half and back-half fragments. The hard part is deciding which continuation fragments belong together when MinerU drops, mutates, or glues marker text.

This is a good boundary for an LLM:

- the input set is small
- the task is narrow
- the LLM only needs to match fragments, not rewrite them
- repository code can still own the final merge and cleanup behavior

## Parsing Model

The parser should move from directly producing final page articles toward producing article fragments first.

Each fragment should include at least:

- `title`
- `body_text`
- `source_order`
- `continued_to_page`
- `continued_from_page`

`source_order` is the fragment order in the parsed Markdown stream. It is not a printed page number. It exists so downstream matching and merge logic can preserve document order.

`continued_to_page` is extracted from marker text such as:

- `Please turn to page A7`
- `PleaseturntopageA7`

`continued_from_page` is extracted from marker text such as:

- `Continued from PageOne`
- `Continued from pageR1`

When no marker is present, the continuation field should be empty.

## Detection Rules

The repository should add deterministic marker extraction helpers for:

### Front-half markers

Recognize variants of:

- `Please turn to page A7`
- `PleaseturntopageA7`
- `turn to page A9`

These usually appear at the end of a fragment and imply the fragment continues elsewhere.

### Back-half markers

Recognize variants of:

- `Continued from PageOne`
- `Continued from pageR1`
- `Continued from page A2`

These usually appear at the beginning of a fragment and imply the fragment started elsewhere.

### Boundary cleanup only

Marker cleanup should only touch the local continuation boundary:

- remove the `Please turn to ...` suffix from the front half
- remove the `Continued from ...` prefix from the back half
- repair nearby glued text where MinerU merges marker text with neighboring words
- repair nearby broken hyphenation if the split happens exactly at the merge boundary

This slice should not attempt general cleanup across the whole article body.

## LLM Matching Step

After fragment parsing finishes, collect only fragments that have at least one of:

- `continued_to_page`
- `continued_from_page`

The LLM should receive these continuation-bearing fragments and return only the continuation matches.

The LLM task is:

- find which `continued_to` fragment matches which `continued_from` fragment
- return the matched fragment ids or indexes

The LLM should not be asked to:

- summarize
- explain its reasoning
- produce a confidence score
- rewrite article text

The repository should treat the LLM as a narrow matcher, not as a formatter or editor.

## Merge Semantics

Once a fragment pair is matched:

- keep the front fragment title as the final title by default
- append cleaned back-half body text to the cleaned front-half body text
- preserve front-half then back-half reading order
- remove continuation markers from the final body
- apply only local boundary cleanup for glued text or split words

If a continuation-bearing fragment is not matched by the LLM:

- leave it as a standalone article fragment in the current output
- do not guess a match deterministically in this slice

## Error Handling

- If continuation detection fails, the fragment remains a normal standalone article
- If the LLM matching call fails, the document should still return unmerged fragments rather than hard-failing the whole parse
- If the LLM returns malformed or impossible matches, ignore those matches and keep the original fragments
- One back-half fragment should not be merged into multiple front-half fragments

## Testing Strategy

This slice should be implemented with strict TDD.

Recommended red-green sequence:

1. add a failing parser test that captures `continued_to_page` from `Please turn to page A7`
2. add a failing parser test that captures `continued_from_page` from `Continued from PageOne`
3. add a failing merge test for one matched pair
4. add a failing merge test that removes marker text from both sides
5. add a failing merge test that repairs glued marker-boundary text
6. add a failing integration test where a fake matcher pairs two continuation fragments and the final article output is merged

The tests should keep using repository-native fake matching rather than a live LLM call.

## Implementation Notes

- The current Markdown parser in `pdf.py` is still the right place for first-pass fragment extraction
- The LLM-matching boundary should be introduced as a small injectable dependency so tests can supply a fake matcher
- The parser entry should continue to work without a live LLM by leaving fragments unmerged when no matcher is provided

## Success Criteria

This slice should be considered successful when the repository can:

- detect explicit continuation markers from MinerU Markdown
- preserve those markers as structured fragment metadata
- match continuation pairs through an injected matcher
- merge matched fragments into one final article
- remove local continuation-marker noise without broad OCR cleanup
