# Economist QQ Super-Large-Attachment Email Download — Design

Date: 2026-06-15

## Problem

A new email source delivers the weekly Economist e-edition: sender `灯塔外刊
<903817461@qq.com>` sends the PDF as a QQ "超大附件" (super-large attachment),
not a normal MIME attachment. The message body contains two "进入下载页面" links —
one for the English original (`TE-2026-06-13-PDF_WEB.pdf`) and one for the
Chinese translation (`【译】TE-2026-06-13-PDF_WEB.pdf`). Each link points to a QQ
landing URL of the form `https://wx.mail.qq.com/ftn/download?func=3&k=…&key=…&code=…`.

We want the importer to automatically download **only the English original** from
this source and feed it into the existing Economist e-edition parse path.

## What already works (verified against the live link)

The existing Gmail body-link download pipeline already covers almost the entire
flow. Confirmed end-to-end against a real link from the sample email:

1. Body-link extraction parses `<a href>` URLs from the HTML part.
2. `wx.mail.qq.com` is already in `allowed_link_domains`.
3. `_is_qq_mail_landing_page` matches `wx.mail.qq.com` + `/ftn/download`.
4. `HttpLinkDownloader.resolve_download_url` POSTs `f=json` to the landing URL.
   The live response is:
   ```json
   {"head":{"ret":0,...},
    "body":{"url":"https://wx.mail.qq.com/ftn/download?func=4&key=…&code=…",
            "name":"TE-2026-06-13-PDF_WEB.pdf","size":12818496, ...}}
   ```
5. `download_binary(body.url)` follows the func=4 → 302 redirect to
   `gzc-dfsdown.mail.ftn.qq.com`; `requests` carries the `mail5k` cookie across
   the redirect chain, and the final response is `%PDF-1.4`,
   `content-type: application/pdf`. (Plain `curl -L` without a cookie engine
   gets a 400 — only `requests`-style cookie propagation succeeds. This is
   already what the production downloader does.)
6. A downloaded `TE-*-PDF_WEB.pdf` already routes to the Economist edition parser.

## The gap

`resolve_download_url` returns **only the resolved URL string and discards the
JSON `name`**. Downstream, `_build_attachment_from_url` derives the filename via
`_filename_from_url(resolved_url)`. The resolved func=4 URL's path is
`/ftn/download` (the real filename lives only in the later 302 `Location`), so
**every QQ super-large attachment is named `download.pdf`**.

Consequences:

- **Translated-file filter fails.** `_is_translated_pdf_filename` is filename-based.
  With both links collapsing to `download.pdf`, the `【译】` translation is **not**
  filtered — it would be downloaded (~12 MB), imported, and parsed, wasting
  bandwidth/compute and producing a wrong-language result.
- **Filename signals lost.** Publication-date dedupe, source-name extraction, and
  Economist filename heuristics all rely on the real `TE-*-PDF_WEB.pdf` name.

## Approach

Thread the real filename from the QQ JSON `name` through the resolver, and use it
to filter the translation **before** the large download.

### Resolver returns url + filename

Change the QQ landing-page resolution to return both the resolved URL and the
real filename, instead of a bare `str | None`. Introduce a small immutable
result type:

```python
@dataclass(frozen=True)
class ResolvedDownload:
    url: str
    filename: str | None = None
```

- `HttpLinkDownloader.resolve_download_url` returns `ResolvedDownload(url=body["url"],
  filename=body.get("name"))` (or `None` when it cannot resolve).
- The `_resolve_download_url` helper and `_build_attachment_from_url` are updated
  to consume the new type.

Only the QQ landing-page path implements `resolve_download_url` today, so the
blast radius is one production method plus the test double.

### Filter the translation before downloading

The caller (`_extract_pdf_links_from_message_body`, gmail.py ~566) already
filters by `attachment.filename`: when `_is_translated_pdf_filename(filename)` is
true it emits the `body_link_filename_filtered` audit item and drops the
attachment. The only reason that filter misses today is that the filename is
`download.pdf`. So the fix is to give the attachment its **real name** — the
existing caller logic then does the right thing.

In `_build_attachment_from_url`'s resolver branch, when a `ResolvedDownload`
carries a `filename`:

1. Compute `filename = resolved.filename or _filename_from_url(resolved.url)`.
2. If `resolved.filename` is present and `_is_translated_pdf_filename(filename)`
   → build the attachment with the **real name and empty `content_bytes`**, skipping
   the `download_binary` call. The caller filters it out by name (never reading
   the bytes) and emits `body_link_filename_filtered`. This avoids the ~12 MB
   transfer for the translation.
3. Otherwise download `resolved.url` and build the attachment with `filename`.

When `resolved.filename` is absent (non-QQ resolvers, or QQ JSON without `name`),
behavior is identical to today via the `_filename_from_url` fallback. The English
original keeps its correct `TE-*-PDF_WEB.pdf` name, so dedupe / source-name /
Economist routing are reused unchanged.

### Config

Add `903817461@qq.com` to `allowed_senders` in `config/gmail-config.json`. No
domain-allowlist change — `wx.mail.qq.com` is already present. Update
`.env.example`/docs only if they enumerate senders.

## Components touched

- `src/newspaper_translator/gmail.py`
  - New `ResolvedDownload` dataclass.
  - `HttpLinkDownloader.resolve_download_url` → returns `ResolvedDownload | None`,
    capturing `body["name"]`.
  - `_resolve_download_url` helper → returns `ResolvedDownload | None`.
  - `_build_attachment_from_url` → translated-name pre-filter + real-filename use.
- `config/gmail-config.json` — add sender.
- `tests/test_gmail.py` — update the QQ landing-page test double and assertions;
  add cases for (a) English original imported with correct name, (b) translated
  super-large attachment skipped before download.

## Data flow (new email)

```
HTML body → anchor hrefs (2 × wx.mail.qq.com func=3)
  → allowed_link_domains? yes
  → resolve_download_url (POST f=json) → ResolvedDownload(url=func4, name)
      name is 【译】…  → attachment(name=【译】…, bytes=b""), no download
                        → caller filters by name → body_link_filename_filtered
      name is TE-…    → download_binary(func4) → %PDF → GmailAttachment(name=TE-…)
  → import → economist edition parse path (unchanged)
```

## Error handling

- Resolution failure (`resolve_download_url` raises / returns `None`): unchanged —
  falls through to the existing direct-PDF / HTML-scrape branches, then audited
  `link_not_importable`.
- `requests.RequestException` during resolve/download: unchanged — audited
  `link_fetch_failed`.
- Missing `name` in JSON: `filename=None` → behaves exactly as today
  (`_filename_from_url` fallback). No regression for non-QQ links.

## Testing

- Unit (test_gmail.py): English original → one document with name
  `TE-2026-06-13-PDF_WEB.pdf`; translated super-large attachment → skipped,
  `body_link_filename_filtered` audit item, downloader's `download_binary` never
  called for it.
- Existing QQ/dengtazk/body-link tests stay green after the return-type change.

## Out of scope

- No change to the Economist parser, persistence, or enrichment.
- No support for normal (non-super-large) QQ attachments — not used by this source.
- No new download mechanism for the `mail.qq.com` web UI; the func=3 JSON
  resolution is sufficient and verified.
