# Multi-Round Article Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two single-shot enrichment LLM calls with one multi-round conversation that runs four sequential steps (ad-judgment → translation → summary → tagging) with per-step rewind retries, partial persistence, and a per-step article stage model on `current_step`.

**Architecture:** A provider-agnostic `enrichment_conversation.py` holds the four step prompt/parse definitions plus a `MultiRoundArticleEnricher` driver that owns the conversation history and retry/rewind/short-circuit logic. DeepSeek and Gemini shrink to thin "send(messages)→text" adapters wrapped by `*ArticleEnricher` classes. `enrich_article` consumes one `enricher` and maps its `EnrichmentResult` to the existing enrichment tables; `process_article_processing_run` feeds it an `on_step_advance` callback that writes the new `current_step` stages live.

**Tech Stack:** Python 3.11 (stdlib `urllib`/`json`, `unittest`), SQLite, vanilla-JS frontend. Tests run with `.venv/bin/python -m pytest`.

---

## Background facts for the implementer

- `llm.py::ChatJsonClient` currently only sends a single user message. DeepSeek's `UrllibTransport` catches `HTTPError` (returns a status code) but lets network errors (`urllib.error.URLError`, which subclasses `OSError`) propagate raw.
- Bad HTTP status raises `LlmProviderError`. The driver must treat **both** `LlmProviderError` and `OSError` as retryable (covers format errors and network failures).
- `GeminiError` subclasses `RuntimeError` (NOT `LlmProviderError`), so the Gemini send-adapter must raise `LlmProviderError` on bad status, not `GeminiError`.
- `get_final_article()` already returns the article with local image links stripped, so the enricher receives clean `title_en`/`body_text_en`.
- Article stages live on `article_processing_runs.current_step` (free-text, no migration). Document stages live on a *different* table (`document_processing_runs.current_step`) and are **out of scope** — do not touch them.
- The existing run-level `STEP_RETRY_LIMIT` (scheduler re-runs of a whole article) is separate from the new in-conversation `ENRICHMENT_STEP_RETRY_LIMIT`.

### Stage keys (article `current_step`)

| key | 中文 |
|---|---|
| `await_ad_judgment` | 等待广告判断 |
| `await_translation` | 等待翻译 |
| `await_summary` | 等待摘要 |
| `await_tagging` | 等待标签 |
| `completed` | 完成 |
| `classified_as_advertisement` | 判定为广告 |

### `EnrichmentResult` contract (defined in Task 2, used everywhere)

```python
@dataclass(frozen=True)
class EnrichmentResult:
    content_type: str | None            # None only when ad-judgment step failed
    classification_reason: str | None
    translation_status: str             # "succeeded" | "failed" | "skipped"
    summary_status: str                 # "succeeded" | "failed" | "skipped"
    tagging_status: str                 # "succeeded" | "failed" | "skipped"
    translated_title_zh: str | None
    translated_body_zh: str | None
    summary_zh: str | None
    tags: list[str]
    failed_step: str | None             # "ad_judgment"|"translation"|"summary"|"tagging"|None
    error_message: str | None
```

Enricher call signature everywhere: `enricher(article, *, on_step_advance=None) -> EnrichmentResult`.
The driver calls `on_step_advance(step_key)` with the raw step key (`"ad_judgment"` etc.) when it enters each step.

---

## Task 1: Multi-turn send in `llm.py`

**Files:**
- Modify: `src/newspaper_translator/llm.py`
- Test: `tests/test_deepseek.py` (ChatJsonClientTests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deepseek.py` inside `class ChatJsonClientTests`:

```python
    def test_complete_json_text_messages_posts_full_history(self) -> None:
        from newspaper_translator.llm import ChatCompletionSettings, ChatJsonClient

        transport = _FakeTransport(
            responses=[
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
                    ).encode("utf-8"),
                )
            ]
        )
        client = ChatJsonClient(
            settings=ChatCompletionSettings(
                api_key="deepseek-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                timeout_seconds=45,
            ),
            transport=transport,
        )

        messages = [
            {"role": "user", "content": "judge"},
            {"role": "assistant", "content": "{\"content_type\": \"article\"}"},
            {"role": "user", "content": "translate"},
        ]
        text = client.complete_json_text_messages(messages)

        self.assertEqual(text, "{\"ok\": true}")
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["messages"], messages)
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_deepseek.py::ChatJsonClientTests::test_complete_json_text_messages_posts_full_history -v`
Expected: FAIL with `AttributeError: 'ChatJsonClient' object has no attribute 'complete_json_text_messages'`

- [ ] **Step 3: Refactor `complete_json_text` onto a messages-based method**

In `src/newspaper_translator/llm.py`, replace the body of `complete_json_text` (lines 51-84) with a delegation, and add the new method directly after it:

```python
    def complete_json_text(self, prompt: str) -> str:
        return self.complete_json_text_messages(
            [{"role": "user", "content": prompt}]
        )

    def complete_json_text_messages(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {
                "type": "json_object",
            },
        }
        response = self._transport.request(
            method="POST",
            url=f"{self._settings.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
            },
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._settings.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise LlmProviderError(f"LLM request failed with status {response.status_code}")
        response_payload = json.loads(response.body.decode("utf-8"))
        try:
            text = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmProviderError("LLM response did not contain a valid text choice") from exc
        if not isinstance(text, str) or not text.strip():
            raise LlmProviderError("LLM response text choice was empty")
        return text.strip()
```

- [ ] **Step 4: Run the llm tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deepseek.py::ChatJsonClientTests -v`
Expected: PASS (all ChatJsonClientTests, including the pre-existing single-prompt test).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/llm.py tests/test_deepseek.py
git commit -m "feat: add multi-turn complete_json_text_messages to ChatJsonClient"
```

---

## Task 2: Step definitions + `EnrichmentResult` in `enrichment_conversation.py`

**Files:**
- Create: `src/newspaper_translator/enrichment_conversation.py`
- Test: `tests/test_enrichment_conversation.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_enrichment_conversation.py`:

```python
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class _Article:
    title_en = "Big Oil Explores Farther Afield"
    body_text_en = "U.S. oil futures were trading near $90 a barrel Sunday."


class StepParsingTests(unittest.TestCase):
    def test_ad_judgment_message_includes_title_and_body(self) -> None:
        from newspaper_translator.enrichment_conversation import build_ad_judgment_message

        message = build_ad_judgment_message(_Article())
        self.assertIn("Big Oil Explores Farther Afield", message)
        self.assertIn("U.S. oil futures", message)

    def test_parse_ad_judgment_returns_type_and_reason(self) -> None:
        from newspaper_translator.enrichment_conversation import parse_ad_judgment

        self.assertEqual(
            parse_ad_judgment(
                {"content_type": "article", "classification_reason": "  normal  "}
            ),
            ("article", "normal"),
        )

    def test_parse_ad_judgment_rejects_bad_content_type(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_ad_judgment,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_ad_judgment({"content_type": "bogus", "classification_reason": ""})

    def test_parse_translation_requires_nonempty_for_article(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_translation,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_translation(
                {"translated_title_zh": "", "translated_body_zh": ""},
                content_type="article",
            )

    def test_parse_translation_allows_empty_for_advertisement(self) -> None:
        from newspaper_translator.enrichment_conversation import parse_translation

        self.assertEqual(
            parse_translation(
                {"translated_title_zh": "", "translated_body_zh": ""},
                content_type="advertisement",
            ),
            ("", ""),
        )

    def test_parse_summary_rejects_multiline(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_summary,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_summary({"summary_zh": "line one\nline two"})

    def test_parse_tags_normalizes_and_enforces_count(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_tags,
        )

        self.assertEqual(
            parse_tags({"tags": ["  经济  ", "经济", "市场", "企业"]}),
            ["经济", "市场", "企业"],
        )
        with self.assertRaises(EnrichmentFormatError):
            parse_tags({"tags": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_enrichment_conversation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newspaper_translator.enrichment_conversation'`

- [ ] **Step 3: Create the module with step definitions**

Create `src/newspaper_translator/enrichment_conversation.py`:

```python
from newspaper_translator.llm import LlmProviderError

STEP_AD_JUDGMENT = "ad_judgment"
STEP_TRANSLATION = "translation"
STEP_SUMMARY = "summary"
STEP_TAGGING = "tagging"


class EnrichmentFormatError(LlmProviderError):
    """Raised when an enrichment step response fails validation."""


def build_ad_judgment_message(article) -> str:
    return (
        "You are processing English newspaper content parsed from a printed newspaper "
        "page. Across this conversation you will classify, translate, summarize, and tag "
        "the SAME article. Step 1: classify ONLY. Most parsed items are normal newspaper "
        "content and must be classified as \"article\". Only classify as \"advertisement\" "
        "when it is very obviously a newspaper advertisement, sponsored or promotional "
        "block, subscription offer, display ad, or advertorial block. Business news, market "
        "coverage, product reporting, reviews, opinion columns, book reviews, real-estate "
        "reporting, job-market reporting, and company profiles are NOT advertisements just "
        "because they mention companies, products, prices, or services. When unsure, "
        "classify as \"uncertain\". return JSON only. Do not use Markdown code fences. Do "
        "not include explanations outside the JSON. Return exactly these fields: "
        '{"content_type":"article|advertisement|uncertain","classification_reason":"..."}.'
        "\n\nTitle:\n"
        f"{article.title_en}\n\nBody:\n{article.body_text_en}\n"
    )


def parse_ad_judgment(payload: dict) -> tuple[str, str]:
    content_type = payload.get("content_type")
    classification_reason = payload.get("classification_reason")
    if content_type not in ("article", "advertisement", "uncertain"):
        raise EnrichmentFormatError(
            f"enrichment ad-judgment has unsupported content_type: {content_type!r}"
        )
    if not isinstance(classification_reason, str):
        raise EnrichmentFormatError(
            "enrichment ad-judgment classification_reason must be a string"
        )
    return content_type, classification_reason.strip()


def build_translation_message() -> str:
    return (
        "Step 2: translate the SAME article shown above into Simplified Chinese. Preserve "
        "continuation markers and jump words exactly when they appear in the source, such "
        'as "Please turn to page A7" or "Continued from Page One". Do not silently remove, '
        "summarize, or normalize those navigation markers. Preserve meaning rather than "
        "literal word order. return JSON only. Do not use Markdown code fences. Do not "
        "include explanations outside the JSON. Return exactly these fields: "
        '{"translated_title_zh":"...","translated_body_zh":"..."}.'
    )


def parse_translation(payload: dict, *, content_type: str) -> tuple[str, str]:
    translated_title_zh = payload.get("translated_title_zh")
    translated_body_zh = payload.get("translated_body_zh")
    if not isinstance(translated_title_zh, str) or not isinstance(translated_body_zh, str):
        raise EnrichmentFormatError(
            "enrichment translation must include string title and body fields"
        )
    if content_type in ("article", "uncertain"):
        if not translated_title_zh.strip() or not translated_body_zh.strip():
            raise EnrichmentFormatError(
                "enrichment translation must include non-empty title and body"
            )
    return translated_title_zh.strip(), translated_body_zh.strip()


def build_summary_message() -> str:
    return (
        "Step 3: write a Simplified Chinese news-card summary of the SAME article. "
        "summary_zh must be a single paragraph with no line breaks. return JSON only. Do "
        "not use Markdown code fences. Do not include explanations. Return exactly this "
        'field: {"summary_zh":"..."}.'
    )


def parse_summary(payload: dict) -> str:
    summary_zh = payload.get("summary_zh")
    if not isinstance(summary_zh, str) or not summary_zh.strip():
        raise EnrichmentFormatError("enrichment summary must include summary_zh")
    if "\n" in summary_zh or "\r" in summary_zh:
        raise EnrichmentFormatError("enrichment summary must be a single paragraph")
    return summary_zh.strip()


def build_tagging_message() -> str:
    return (
        "Step 4: produce ordered Chinese tags for the SAME article. tags must contain 3 to "
        "8 short Chinese phrases with no leading #. return JSON only. Do not use Markdown "
        "code fences. Do not include explanations. Return exactly this field: "
        '{"tags":["...","..."]}.'
    )


def parse_tags(payload: dict) -> list[str]:
    normalized_tags = _normalize_tags(payload.get("tags"))
    if not 3 <= len(normalized_tags) <= 8:
        raise EnrichmentFormatError("enrichment tags must include 3 to 8 non-empty tags")
    return normalized_tags


def _normalize_tags(raw_tags: object) -> list[str]:
    if not isinstance(raw_tags, list):
        raise EnrichmentFormatError("enrichment tags payload must be a list")
    normalized_tags: list[str] = []
    seen_tags: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            raise EnrichmentFormatError("enrichment tags entries must be strings")
        normalized_tag = raw_tag.strip()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        normalized_tags.append(normalized_tag)
        seen_tags.add(normalized_tag)
    return normalized_tags
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_enrichment_conversation.py -v`
Expected: PASS (all 8 step-parsing tests).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/enrichment_conversation.py tests/test_enrichment_conversation.py
git commit -m "feat: add multi-round enrichment step definitions"
```

---

## Task 3: `MultiRoundArticleEnricher` driver

**Files:**
- Modify: `src/newspaper_translator/enrichment_conversation.py`
- Test: `tests/test_enrichment_conversation.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_enrichment_conversation.py` (before the `if __name__` block):

```python
import json as _json


def _chat_text(obj) -> str:
    return _json.dumps(obj)


class _ScriptedSend:
    """Returns queued raw texts; an entry that is an Exception is raised instead."""

    def __init__(self, outputs) -> None:
        self._outputs = list(outputs)
        self.sent_messages = []

    def __call__(self, messages):
        self.sent_messages.append(list(messages))
        nxt = self._outputs.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


class MultiRoundArticleEnricherTests(unittest.TestCase):
    def _all_ok_outputs(self):
        return [
            _chat_text({"content_type": "article", "classification_reason": "normal"}),
            _chat_text({"translated_title_zh": "标题", "translated_body_zh": "正文"}),
            _chat_text({"summary_zh": "一段摘要。"}),
            _chat_text({"tags": ["经济", "市场", "企业"]}),
        ]

    def test_runs_four_steps_and_accumulates_history(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        send = _ScriptedSend(self._all_ok_outputs())
        stages = []
        result = MultiRoundArticleEnricher(send=send)(
            _Article(), on_step_advance=stages.append
        )

        self.assertEqual(
            stages, ["ad_judgment", "translation", "summary", "tagging"]
        )
        self.assertEqual(result.translation_status, "succeeded")
        self.assertEqual(result.summary_status, "succeeded")
        self.assertEqual(result.tagging_status, "succeeded")
        self.assertEqual(result.translated_title_zh, "标题")
        self.assertEqual(result.summary_zh, "一段摘要。")
        self.assertEqual(result.tags, ["经济", "市场", "企业"])
        self.assertIsNone(result.failed_step)
        # Last send carried the whole history: u,a,u,a,u,a,u (7 messages).
        self.assertEqual(len(send.sent_messages[-1]), 7)
        self.assertEqual(send.sent_messages[-1][0]["role"], "user")
        self.assertEqual(send.sent_messages[-1][1]["role"], "assistant")

    def test_advertisement_short_circuits_after_step_one(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        send = _ScriptedSend(
            [_chat_text({"content_type": "advertisement", "classification_reason": "ad"})]
        )
        result = MultiRoundArticleEnricher(send=send)(_Article())

        self.assertEqual(result.content_type, "advertisement")
        self.assertEqual(result.translation_status, "skipped")
        self.assertEqual(result.summary_status, "skipped")
        self.assertEqual(result.tagging_status, "skipped")
        self.assertIsNone(result.failed_step)
        self.assertEqual(len(send.sent_messages), 1)

    def test_retries_a_failed_step_from_last_success(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            MultiRoundArticleEnricher,
        )

        outputs = [
            _chat_text({"content_type": "article", "classification_reason": "normal"}),
            EnrichmentFormatError("bad json"),  # translation attempt 1 fails
            _chat_text({"translated_title_zh": "标题", "translated_body_zh": "正文"}),  # attempt 2 ok
            _chat_text({"summary_zh": "一段摘要。"}),
            _chat_text({"tags": ["经济", "市场", "企业"]}),
        ]
        send = _ScriptedSend(outputs)
        result = MultiRoundArticleEnricher(send=send, step_retry_limit=2)(_Article())

        self.assertEqual(result.translation_status, "succeeded")
        # The retried translation attempt restarted from the 2-message committed history.
        self.assertEqual(len(send.sent_messages[1]), 3)  # u,a,u
        self.assertEqual(len(send.sent_messages[2]), 3)  # retry uses same committed base

    def test_exhausts_retries_and_marks_summary_partial(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        outputs = [
            _chat_text({"content_type": "article", "classification_reason": "normal"}),
            _chat_text({"translated_title_zh": "标题", "translated_body_zh": "正文"}),
            OSError("timeout"),  # summary attempt 1
            OSError("timeout"),  # summary attempt 2 (retry 1)
            OSError("timeout"),  # summary attempt 3 (retry 2)
        ]
        send = _ScriptedSend(outputs)
        result = MultiRoundArticleEnricher(send=send, step_retry_limit=2)(_Article())

        self.assertEqual(result.translation_status, "succeeded")
        self.assertEqual(result.summary_status, "failed")
        self.assertEqual(result.tagging_status, "failed")
        self.assertEqual(result.failed_step, "summary")
        self.assertIn("timeout", result.error_message)
        self.assertEqual(result.translated_title_zh, "标题")
        self.assertIsNone(result.summary_zh)

    def test_ad_judgment_failure_marks_everything_failed(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        send = _ScriptedSend([OSError("net"), OSError("net"), OSError("net")])
        result = MultiRoundArticleEnricher(send=send, step_retry_limit=2)(_Article())

        self.assertIsNone(result.content_type)
        self.assertEqual(result.failed_step, "ad_judgment")
        self.assertEqual(result.translation_status, "skipped")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_enrichment_conversation.py::MultiRoundArticleEnricherTests -v`
Expected: FAIL with `ImportError: cannot import name 'MultiRoundArticleEnricher'`

- [ ] **Step 3: Implement the driver**

Add to the top of `src/newspaper_translator/enrichment_conversation.py` (after the existing `from ... import LlmProviderError`):

```python
import json
from dataclasses import dataclass
```

Append to the end of `src/newspaper_translator/enrichment_conversation.py`:

```python
@dataclass(frozen=True)
class EnrichmentResult:
    content_type: str | None
    classification_reason: str | None
    translation_status: str
    summary_status: str
    tagging_status: str
    translated_title_zh: str | None
    translated_body_zh: str | None
    summary_zh: str | None
    tags: list[str]
    failed_step: str | None
    error_message: str | None


class _StepFailed(Exception):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step
        self.message = message


def _loads_json_object(text: str) -> dict:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EnrichmentFormatError("enrichment response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise EnrichmentFormatError("enrichment response JSON must be an object")
    return payload


class MultiRoundArticleEnricher:
    def __init__(self, *, send, step_retry_limit: int = 2) -> None:
        self._send = send
        self._step_retry_limit = step_retry_limit

    def __call__(self, article, *, on_step_advance=None) -> EnrichmentResult:
        committed: list[dict] = []
        try:
            (content_type, classification_reason), committed = self._run_step(
                committed,
                STEP_AD_JUDGMENT,
                build_ad_judgment_message(article),
                parse_ad_judgment,
                on_step_advance,
            )
        except _StepFailed as failure:
            return _failed_before_translation(failure)

        if content_type == "advertisement":
            return EnrichmentResult(
                content_type="advertisement",
                classification_reason=classification_reason,
                translation_status="skipped",
                summary_status="skipped",
                tagging_status="skipped",
                translated_title_zh=None,
                translated_body_zh=None,
                summary_zh=None,
                tags=[],
                failed_step=None,
                error_message=None,
            )

        try:
            (translated_title_zh, translated_body_zh), committed = self._run_step(
                committed,
                STEP_TRANSLATION,
                build_translation_message(),
                lambda payload: parse_translation(payload, content_type=content_type),
                on_step_advance,
            )
        except _StepFailed as failure:
            return EnrichmentResult(
                content_type=content_type,
                classification_reason=classification_reason,
                translation_status="failed",
                summary_status="skipped",
                tagging_status="skipped",
                translated_title_zh=None,
                translated_body_zh=None,
                summary_zh=None,
                tags=[],
                failed_step=failure.step,
                error_message=failure.message,
            )

        try:
            summary_zh, committed = self._run_step(
                committed,
                STEP_SUMMARY,
                build_summary_message(),
                parse_summary,
                on_step_advance,
            )
        except _StepFailed as failure:
            return EnrichmentResult(
                content_type=content_type,
                classification_reason=classification_reason,
                translation_status="succeeded",
                summary_status="failed",
                tagging_status="failed",
                translated_title_zh=translated_title_zh,
                translated_body_zh=translated_body_zh,
                summary_zh=None,
                tags=[],
                failed_step=failure.step,
                error_message=failure.message,
            )

        try:
            tags, committed = self._run_step(
                committed,
                STEP_TAGGING,
                build_tagging_message(),
                parse_tags,
                on_step_advance,
            )
        except _StepFailed as failure:
            return EnrichmentResult(
                content_type=content_type,
                classification_reason=classification_reason,
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="failed",
                translated_title_zh=translated_title_zh,
                translated_body_zh=translated_body_zh,
                summary_zh=summary_zh,
                tags=[],
                failed_step=failure.step,
                error_message=failure.message,
            )

        return EnrichmentResult(
            content_type=content_type,
            classification_reason=classification_reason,
            translation_status="succeeded",
            summary_status="succeeded",
            tagging_status="succeeded",
            translated_title_zh=translated_title_zh,
            translated_body_zh=translated_body_zh,
            summary_zh=summary_zh,
            tags=tags,
            failed_step=None,
            error_message=None,
        )

    def _run_step(self, committed, step_key, user_message, parse_fn, on_step_advance):
        if on_step_advance is not None:
            on_step_advance(step_key)
        last_error_message = f"{step_key} step failed"
        for _ in range(self._step_retry_limit + 1):
            messages = committed + [{"role": "user", "content": user_message}]
            try:
                text = self._send(messages)
                value = parse_fn(_loads_json_object(text))
            except (LlmProviderError, OSError) as exc:
                last_error_message = str(exc) or last_error_message
                continue
            return value, messages + [{"role": "assistant", "content": text}]
        raise _StepFailed(step_key, last_error_message)


def _failed_before_translation(failure: "_StepFailed") -> EnrichmentResult:
    return EnrichmentResult(
        content_type=None,
        classification_reason=None,
        translation_status="skipped",
        summary_status="skipped",
        tagging_status="skipped",
        translated_title_zh=None,
        translated_body_zh=None,
        summary_zh=None,
        tags=[],
        failed_step=failure.step,
        error_message=failure.message,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_enrichment_conversation.py -v`
Expected: PASS (step-parsing + all 5 driver tests).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/enrichment_conversation.py tests/test_enrichment_conversation.py
git commit -m "feat: add MultiRoundArticleEnricher driver with rewind retries"
```

---

## Task 4: DeepSeek enricher + remove old DeepSeek translator/summarizer

**Files:**
- Modify: `src/newspaper_translator/deepseek.py`
- Test: `tests/test_deepseek.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_deepseek.py`, **delete** these now-obsolete tests from `class DeepSeekClientTests`:
`test_translator_parses_classification_and_translation`, `test_summarizer_tagger_parses_summary_and_tags`, `test_translator_raises_for_unsupported_content_type`, `test_translator_raises_when_article_translation_empty`, `test_translator_allows_empty_translation_for_advertisement`, `test_summarizer_tagger_raises_when_summary_contains_newline`, `test_summarizer_tagger_raises_when_tag_count_below_minimum`, `test_summarizer_tagger_deduplicates_and_strips_tags`.

Then add this test class to `tests/test_deepseek.py` (before the `_FakeResponse` definition):

```python
class DeepSeekArticleEnricherTests(unittest.TestCase):
    def test_runs_full_multi_round_conversation(self) -> None:
        from newspaper_translator.deepseek import DeepSeekArticleEnricher

        enricher = DeepSeekArticleEnricher(
            settings=_deepseek_settings(),
            transport=_FakeTransport(
                responses=[
                    _chat_response(
                        {"content_type": "article", "classification_reason": "normal"}
                    ),
                    _chat_response(
                        {"translated_title_zh": "标题", "translated_body_zh": "正文"}
                    ),
                    _chat_response({"summary_zh": "一段摘要。"}),
                    _chat_response({"tags": ["经济", "市场", "企业"]}),
                ]
            ),
        )

        result = enricher(_stored_article())

        self.assertEqual(result.content_type, "article")
        self.assertEqual(result.translated_title_zh, "标题")
        self.assertEqual(result.summary_zh, "一段摘要。")
        self.assertEqual(result.tags, ["经济", "市场", "企业"])
        self.assertEqual(result.tagging_status, "succeeded")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_deepseek.py::DeepSeekArticleEnricherTests -v`
Expected: FAIL with `ImportError: cannot import name 'DeepSeekArticleEnricher'`

- [ ] **Step 3: Rewrite `deepseek.py`**

In `src/newspaper_translator/deepseek.py`: remove the `from newspaper_translator.gemini import (...)` import block (lines 5-8), remove the `StoredFinalArticle` import if now unused, and **delete** the entire `DeepSeekArticleTranslator` class (lines 91-163) and `DeepSeekArticleSummarizerTagger` class + module-level `_normalize_tags` (lines 166-249). Keep `DeepSeekError`, `_chat_settings_from_deepseek`, and `DeepSeekContinuationMatcher`.

Add these imports at the top:

```python
from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher
```

Append this class to `src/newspaper_translator/deepseek.py`:

```python
class DeepSeekArticleEnricher:
    def __init__(
        self,
        *,
        settings: DeepSeekSettings,
        transport: Transport | None = None,
        step_retry_limit: int = 2,
    ) -> None:
        client = ChatJsonClient(
            settings=_chat_settings_from_deepseek(settings),
            transport=transport,
        )

        def send(messages: list[dict[str, str]]) -> str:
            return client.complete_json_text_messages(messages)

        self._driver = MultiRoundArticleEnricher(
            send=send,
            step_retry_limit=step_retry_limit,
        )

    def __call__(self, article, *, on_step_advance=None):
        return self._driver(article, on_step_advance=on_step_advance)
```

- [ ] **Step 4: Run the DeepSeek tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deepseek.py -v`
Expected: PASS (ChatJsonClientTests, the continuation-matcher tests, and the new enricher test).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/deepseek.py tests/test_deepseek.py
git commit -m "feat: add DeepSeekArticleEnricher, remove single-shot DeepSeek classes"
```

---

## Task 5: Gemini enricher + remove old Gemini translator/summarizer

**Files:**
- Modify: `src/newspaper_translator/gemini.py`
- Test: `tests/test_gemini.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_gemini.py`: delete the import of `GeminiArticleTranslator`, `GeminiArticleSummarizerTagger` and the `GeminiArticleTranslatorTests` class (and any `GeminiArticleSummarizerTaggerTests` class). Add a new test class. First read `tests/test_gemini.py` to mirror its existing `_FakeTransport`/response-builder helpers and `_minimal_article()` shape, then add:

```python
class GeminiArticleEnricherTests(unittest.TestCase):
    def test_runs_full_multi_round_conversation(self) -> None:
        from newspaper_translator.config import GeminiSettings
        from newspaper_translator.gemini import GeminiArticleEnricher

        enricher = GeminiArticleEnricher(
            settings=GeminiSettings(
                api_token="gemini-key",
                base_url="https://nuoapi.com/v1beta",
                api_compat_mode="openai_compatible",
                model="gemini-2.5-flash",
                timeout_seconds=45,
            ),
            transport=_openai_transport(
                [
                    {"content_type": "article", "classification_reason": "normal"},
                    {"translated_title_zh": "标题", "translated_body_zh": "正文"},
                    {"summary_zh": "一段摘要。"},
                    {"tags": ["经济", "市场", "企业"]},
                ]
            ),
        )

        result = enricher(self._minimal_article())

        self.assertEqual(result.translated_title_zh, "标题")
        self.assertEqual(result.tags, ["经济", "市场", "企业"])
        self.assertEqual(result.tagging_status, "succeeded")
```

Add a helper `_openai_transport(payloads)` near the test's other helpers that returns a fake transport yielding OpenAI-shaped chat responses (`{"choices":[{"message":{"content": json.dumps(p)}}]}`) for each payload, mirroring the existing `_FakeTransport` already in the file. Reuse the file's existing `_minimal_article()` for `self._minimal_article()` (make it a method or module helper as fits the file).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gemini.py::GeminiArticleEnricherTests -v`
Expected: FAIL with `ImportError: cannot import name 'GeminiArticleEnricher'`

- [ ] **Step 3: Rewrite `gemini.py`**

In `src/newspaper_translator/gemini.py`: delete the `ArticleTranslationResult` and `ArticleSummaryTagResult` dataclasses (lines 18-29), the `GeminiArticleTranslator` class (lines 125-208), the `GeminiArticleSummarizerTagger` class (lines 211-285), and the module-level `_normalize_tags` (lines 288-302). Keep `GeminiError`, `GeminiContinuationMatcher`, `_extract_response_text`, `_build_generate_content_url`, `_build_request_headers`, `_build_request_payload`, and `_UrllibTransport`.

Add imports at the top:

```python
from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher
from newspaper_translator.llm import LlmProviderError
```

Add a messages→payload helper and the enricher class. Append:

```python
def _build_messages_payload(*, settings: GeminiSettings, messages: list[dict[str, str]]) -> dict[str, object]:
    if settings.api_compat_mode == "openai_compatible":
        return {
            "model": settings.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    contents = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message["content"]}]})
    return {
        "contents": contents,
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }


class GeminiArticleEnricher:
    def __init__(
        self,
        *,
        settings: GeminiSettings,
        transport: _Transport | None = None,
        step_retry_limit: int = 2,
    ) -> None:
        self._settings = settings
        self._transport = transport or _UrllibTransport()
        self._driver = MultiRoundArticleEnricher(
            send=self._send,
            step_retry_limit=step_retry_limit,
        )

    def _send(self, messages: list[dict[str, str]]) -> str:
        response = self._transport.request(
            method="POST",
            url=_build_generate_content_url(self._settings),
            headers=_build_request_headers(self._settings),
            body=json.dumps(
                _build_messages_payload(settings=self._settings, messages=messages)
            ).encode("utf-8"),
            timeout=self._settings.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise LlmProviderError(f"Gemini request failed with status {response.status_code}")
        return _extract_response_text(response.body)

    def __call__(self, article, *, on_step_advance=None):
        return self._driver(article, on_step_advance=on_step_advance)
```

Note: `_extract_response_text` raises `GeminiError` (a `RuntimeError`) on a malformed body. To make malformed Gemini responses retryable by the driver, change `_extract_response_text` to raise `LlmProviderError` instead of `GeminiError` (update its `raise GeminiError(...)` to `raise LlmProviderError(...)`). The `GeminiContinuationMatcher` does not call `_extract_response_text`, so this is safe.

- [ ] **Step 4: Run the Gemini tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gemini.py -v`
Expected: PASS (continuation-matcher tests + new enricher test).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/gemini.py tests/test_gemini.py
git commit -m "feat: add GeminiArticleEnricher, remove single-shot Gemini classes"
```

---

## Task 6: Refactor `enrich_article` to consume one enricher

**Files:**
- Modify: `src/newspaper_translator/article_enrichment.py`
- Test: `tests/test_article_enrichment.py`

- [ ] **Step 1: Rewrite the test fakes and calls**

In `tests/test_article_enrichment.py`:

Replace the gemini import (line 23) with:

```python
    from newspaper_translator.enrichment_conversation import EnrichmentResult
```

and in the `except ImportError` block replace `ArticleSummaryTagResult = None` / `ArticleTranslationResult = None` with `EnrichmentResult = None`.

Replace the fake classes at the bottom (`_FakeTranslator`, `_CountingTranslator`, `_CapturingTranslator`, `_FailingTranslator`, `_FakeSummarizerTagger`, `_CountingSummarizerTagger`, `_FailingSummarizerTagger`, `_AdvertisementTranslator`, `_UncertainTranslator`) with enricher fakes:

```python
def _ok_result(content_type="article"):
    return EnrichmentResult(
        content_type=content_type,
        classification_reason="Regular newspaper article.",
        translation_status="succeeded",
        summary_status="succeeded",
        tagging_status="succeeded",
        translated_title_zh="大型石油公司远赴他处避开中东动荡",
        translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
        summary_zh="油企为避开中东风险，正把勘探重点转向非洲和南美。",
        tags=["能源", "石油", "中东局势"],
        failed_step=None,
        error_message=None,
    )


class _FakeEnricher:
    def __call__(self, article, *, on_step_advance=None):
        return _ok_result()


class _CountingEnricher:
    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, article, *, on_step_advance=None):
        self.call_count += 1
        return _ok_result()


class _CapturingEnricher:
    def __init__(self) -> None:
        self.article = None

    def __call__(self, article, *, on_step_advance=None):
        self.article = article
        return _ok_result()


class _FailingTranslationEnricher:
    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, article, *, on_step_advance=None):
        return EnrichmentResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translation_status="failed",
            summary_status="skipped",
            tagging_status="skipped",
            translated_title_zh=None,
            translated_body_zh=None,
            summary_zh=None,
            tags=[],
            failed_step="translation",
            error_message=self._message,
        )


class _FailingSummaryEnricher:
    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, article, *, on_step_advance=None):
        return EnrichmentResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translation_status="succeeded",
            summary_status="failed",
            tagging_status="failed",
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
            summary_zh=None,
            tags=[],
            failed_step="summary",
            error_message=self._message,
        )


class _AdvertisementEnricher:
    def __call__(self, article, *, on_step_advance=None):
        return EnrichmentResult(
            content_type="advertisement",
            classification_reason="Display ad for jewelry retailer.",
            translation_status="skipped",
            summary_status="skipped",
            tagging_status="skipped",
            translated_title_zh=None,
            translated_body_zh=None,
            summary_zh=None,
            tags=[],
            failed_step=None,
            error_message=None,
        )


class _UncertainEnricher:
    def __call__(self, article, *, on_step_advance=None):
        return _ok_result(content_type="uncertain")
```

Update every `enrich_article(...)` call in this file: replace the `translator=...,` and `summarizer_tagger=...,` argument pair with a single `enricher=...,` argument. Mapping for the existing tests:
- `translator=_CapturingTranslator(), summarizer_tagger=_FakeSummarizerTagger()` → keep a `capturing = _CapturingEnricher()` and pass `enricher=capturing`; assert on `capturing.article`.
- `translator=_FakeTranslator(), summarizer_tagger=_FakeSummarizerTagger()` → `enricher=_FakeEnricher()`.
- `_FailingSummarizerTagger("summary timeout")` test → `enricher=_FailingSummaryEnricher("summary timeout")`.
- `_FailingTranslator("translation timeout")` test → `enricher=_FailingTranslationEnricher("translation timeout")`.
- The reuse test uses `_CountingTranslator()` + `_CountingSummarizerTagger()` → use one `enricher=_CountingEnricher()` shared across both calls, and assert `enricher.call_count == 1` (drop the separate summarizer count assertion).
- `_AdvertisementTranslator()` test → `enricher=_AdvertisementEnricher()`; drop the `summarizer.call_count == 0` assertion (no separate summarizer now).
- `_UncertainTranslator()` test → `enricher=_UncertainEnricher()`; drop the `summarizer.call_count == 1` assertion.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_article_enrichment.py -v`
Expected: FAIL — `enrich_article()` got an unexpected keyword argument `enricher` (signature still expects translator/summarizer_tagger).

- [ ] **Step 3: Rewrite `enrich_article`**

Replace the whole body of `src/newspaper_translator/article_enrichment.py`'s `enrich_article` (lines 15-127) with:

```python
def enrich_article(
    *,
    database_url: str,
    article_id: str,
    enricher,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    on_step_advance=None,
    force_reenrich: bool = False,
) -> ArticleEnrichmentRun:
    article = get_final_article(
        database_url=database_url,
        article_id=article_id,
    )
    input_hash = build_article_input_hash(article)
    if not force_reenrich:
        reusable_run = find_successful_article_enrichment_by_article_key_and_input_hash(
            database_url=database_url,
            article_key=article.article_key,
            input_hash=input_hash,
        )
        if reusable_run is not None:
            return reusable_run
    enrichment_run = create_article_enrichment_run(
        database_url=database_url,
        article_id=article.article_id,
        parse_run_id=article.parse_run_id,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        input_hash=input_hash,
    )

    try:
        result = enricher(article, on_step_advance=on_step_advance)
    except Exception as exc:  # noqa: BLE001
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="failed",
            error_message=str(exc),
        )
        return get_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
        )

    if result.content_type == "advertisement":
        record_article_enrichment_outputs(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            translated_title_zh=None,
            summary_zh=None,
            translated_body_zh=None,
            translation_status="skipped",
            summary_status="skipped",
            tagging_status="skipped",
            tags=[],
            content_type="advertisement",
            classification_reason=result.classification_reason or "",
        )
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="skipped_advertisement",
        )
    elif result.translation_status != "succeeded":
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status="failed",
            error_message=result.error_message
            or "article enrichment failed before translation",
        )
    else:
        record_article_enrichment_outputs(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            translated_title_zh=result.translated_title_zh,
            summary_zh=result.summary_zh if result.summary_status == "succeeded" else None,
            translated_body_zh=result.translated_body_zh,
            translation_status="succeeded",
            summary_status=result.summary_status,
            tagging_status=result.tagging_status,
            tags=result.tags if result.tagging_status == "succeeded" else [],
            content_type=result.content_type,
            classification_reason=result.classification_reason or "",
        )
        if result.summary_status == "succeeded" and result.tagging_status == "succeeded":
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="succeeded",
            )
        else:
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="partial",
                error_message=result.error_message,
            )

    return get_article_enrichment_run(
        database_url=database_url,
        enrichment_run_id=enrichment_run.enrichment_run_id,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_article_enrichment.py -v`
Expected: PASS (all enrichment tests, including the advertisement, uncertain, partial, and reuse cases).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/article_enrichment.py tests/test_article_enrichment.py
git commit -m "feat: enrich_article consumes one multi-round enricher"
```

---

## Task 7: Article stage helper + stage-aware success/creation

**Files:**
- Modify: `src/newspaper_translator/document_processing.py`
- Test: `tests/test_process_article.py`

- [ ] **Step 1: Write the failing test**

First read `tests/test_process_article.py` (it uses the shared `_document_processing_helpers`). Add a test that drives the live stage callback. Add to the test file (adapt imports to match the file's existing pattern of importing from `_document_processing_helpers`):

```python
    def test_advances_current_step_through_stages_to_completed(self) -> None:
        from newspaper_translator.document_processing import (
            advance_article_processing_step,
            get_article_processing_run,
        )
        # Build an enricher that emits each step then succeeds.
        from newspaper_translator.enrichment_conversation import EnrichmentResult

        seen_stages = []

        class _StageEnricher:
            def __call__(self, article, *, on_step_advance=None):
                for step in ("ad_judgment", "translation", "summary", "tagging"):
                    if on_step_advance is not None:
                        on_step_advance(step)
                return EnrichmentResult(
                    content_type="article",
                    classification_reason="ok",
                    translation_status="succeeded",
                    summary_status="succeeded",
                    tagging_status="succeeded",
                    translated_title_zh="标题",
                    translated_body_zh="正文",
                    summary_zh="摘要。",
                    tags=["a", "b", "c"],
                    failed_step=None,
                    error_message=None,
                )

        # (Use the file's existing fixture to create an article + processing run,
        #  then call process_article_processing_run with enricher=_StageEnricher()
        #  and assert the final run.current_step == "completed".)
```

Because the exact fixture wiring depends on helpers in this file, the concrete assertion to add is: after `process_article_processing_run(..., enricher=_StageEnricher())`, `get_article_processing_run(...).current_step == "completed"`. Also add a second test using an advertisement enricher asserting `current_step == "classified_as_advertisement"`. (Full fixture setup mirrors the file's existing `process_article` tests — reuse their article-creation helper.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_process_article.py -v`
Expected: FAIL — `ImportError: cannot import name 'advance_article_processing_step'` (and/or stage assertions failing).

- [ ] **Step 3: Add stage constants, helper, and stage-aware success**

In `src/newspaper_translator/document_processing.py`, add near the top (after imports, before the first dataclass):

```python
ARTICLE_STAGE_AWAIT_AD_JUDGMENT = "await_ad_judgment"
ARTICLE_STAGE_AWAIT_TRANSLATION = "await_translation"
ARTICLE_STAGE_AWAIT_SUMMARY = "await_summary"
ARTICLE_STAGE_AWAIT_TAGGING = "await_tagging"
ARTICLE_STAGE_COMPLETED = "completed"
ARTICLE_STAGE_ADVERTISEMENT = "classified_as_advertisement"

_ENRICH_STEP_TO_ARTICLE_STAGE = {
    "ad_judgment": ARTICLE_STAGE_AWAIT_AD_JUDGMENT,
    "translation": ARTICLE_STAGE_AWAIT_TRANSLATION,
    "summary": ARTICLE_STAGE_AWAIT_SUMMARY,
    "tagging": ARTICLE_STAGE_AWAIT_TAGGING,
}


def advance_article_processing_step(
    *,
    database_url: str,
    article_key: str,
    current_step: str,
) -> None:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            connection.execute(
                """
                UPDATE article_processing_runs
                SET current_step = ?, updated_at = CURRENT_TIMESTAMP
                WHERE article_key = ?
                """,
                (current_step, article_key),
            )
            connection.commit()
        finally:
            connection.close()

    _run_with_database_retries(callback)
```

Change `succeed_article_processing_run` (line 1251) to accept a `current_step` parameter and use it:

```python
def succeed_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    last_success_input_hash: str,
    current_step: str = "completed",
) -> ArticleProcessingRun:
```

and in its UPDATE replace `current_step = 'completed',` with `current_step = ?,`, adding `current_step` as the first bound parameter (before `last_success_input_hash`):

```python
                (
                    current_step,
                    last_success_input_hash,
                    article_key,
                ),
```

Change the initial creation `current_step` (line 339) from `"enrich"` to `"await_ad_judgment"`. Change the re-pending branch `current_step = 'enrich',` (line 384) to `current_step = 'await_ad_judgment',`. In the unchanged-hash success shortcut (the `elif last_success_input_hash == input_hash` branch, line ~366), **delete** the line `current_step = 'completed',` so an existing terminal stage (e.g. `classified_as_advertisement`) is preserved.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_article.py -v`
Expected: the import resolves; stage tests pass once Task 8 wires the callback. (If the stage-transition assertions still fail here because `process_article_processing_run` is not yet wired, move those two assertions' verification to the end of Task 8 — keep the import/helper test green now.)

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/document_processing.py tests/test_process_article.py
git commit -m "feat: add article stage keys and live current_step advance helper"
```

---

## Task 8: Wire enricher + live stages into `process_article_processing_run` and `enrich_document_articles`

**Files:**
- Modify: `src/newspaper_translator/document_processing.py`
- Test: `tests/_document_processing_helpers.py`, `tests/test_process_article.py`, `tests/test_process_document.py`, `tests/test_drain.py`

- [ ] **Step 1: Update the shared test fakes**

In `tests/_document_processing_helpers.py`: replace the gemini import (line 30) with `from newspaper_translator.enrichment_conversation import EnrichmentResult` (and update the `except ImportError` fallbacks `ArticleSummaryTagResult = None` / `ArticleTranslationResult = None` to `EnrichmentResult = None`). Replace `_FakeTranslator`, `_FakeSummarizerTagger`, `_FailingSummarizerTagger`, `_SelectiveFailingTranslator` (and any related fakes around lines 512-552) with enricher fakes:

```python
def _ok_enrichment_result(content_type="article"):
    return EnrichmentResult(
        content_type=content_type,
        classification_reason="Regular newspaper article.",
        translation_status="succeeded",
        summary_status="succeeded",
        tagging_status="succeeded",
        translated_title_zh="标题",
        translated_body_zh="正文",
        summary_zh="一段摘要。",
        tags=["经济", "市场", "企业"],
        failed_step=None,
        error_message=None,
    )


class _FakeEnricher:
    def __call__(self, article, *, on_step_advance=None):
        if on_step_advance is not None:
            for step in ("ad_judgment", "translation", "summary", "tagging"):
                on_step_advance(step)
        return _ok_enrichment_result()


class _FailingSummaryEnricher:
    def __init__(self, message: str = "summary timeout") -> None:
        self._message = message

    def __call__(self, article, *, on_step_advance=None):
        if on_step_advance is not None:
            for step in ("ad_judgment", "translation", "summary"):
                on_step_advance(step)
        return EnrichmentResult(
            content_type="article",
            classification_reason="ok",
            translation_status="succeeded",
            summary_status="failed",
            tagging_status="failed",
            translated_title_zh="标题",
            translated_body_zh="正文",
            summary_zh=None,
            tags=[],
            failed_step="summary",
            error_message=self._message,
        )
```

If `_SelectiveFailingTranslator` was used to fail only specific articles (test_process_document line 281), add an equivalent `_SelectiveFailingEnricher(titles_to_fail)` that returns a `failed_step="translation"` result for matching `article.title_en` and `_ok_enrichment_result()` otherwise.

- [ ] **Step 2: Update the calling tests to pass `enricher=`**

In `tests/test_process_article.py`, `tests/test_process_document.py`, `tests/test_drain.py`: change every call that passed `translator=...` and `summarizer_tagger=...` into a single `enricher=...` argument. Concrete substitutions:
- `translator=_FakeTranslator(), summarizer_tagger=_FakeSummarizerTagger()` → `enricher=_FakeEnricher()`
- `summarizer_tagger=_FailingSummarizerTagger(...)` + `_FakeTranslator()` → `enricher=_FailingSummaryEnricher(...)`
- `translator=_SelectiveFailingTranslator(...)` → `enricher=_SelectiveFailingEnricher(...)`
- `translator=mock.Mock(side_effect=RuntimeError("translation timeout"))` (test_drain line 1169-1188) → `enricher=mock.Mock(side_effect=RuntimeError("translation timeout"))` (the enricher raising propagates to `enrich_article`'s outer except → failed run, preserving the test's intent).
- inline `translator=lambda _article: ArticleTranslationResult(...)` + `summarizer_tagger=lambda **kwargs: ArticleSummaryTagResult(...)` (test_process_article lines 73-83, 143-153; test_drain 1366-1376, 1443+) → a single `enricher=lambda _article, on_step_advance=None: EnrichmentResult(content_type="article", classification_reason="ok", translation_status="succeeded", summary_status="succeeded", tagging_status="succeeded", translated_title_zh="标题", translated_body_zh="正文", summary_zh="摘要。", tags=["a","b","c"], failed_step=None, error_message=None)` (import `EnrichmentResult` from `newspaper_translator.enrichment_conversation`).
- Remove now-dead imports/assertions of `ArticleTranslationResult`/`ArticleSummaryTagResult` in these files.

- [ ] **Step 3: Rewrite the signatures and wiring in `document_processing.py`**

In `process_article_processing_run` (line 1291): replace params `translator,` and `summarizer_tagger,` (lines 1296-1297) with `enricher,`. Replace the enrich call + terminal handling (lines 1327-1353) with:

```python
    def _advance_stage(step_key: str) -> None:
        advance_article_processing_step(
            database_url=database_url,
            article_key=article_key,
            current_step=_ENRICH_STEP_TO_ARTICLE_STAGE[step_key],
        )

    last_stage = {"value": ARTICLE_STAGE_AWAIT_AD_JUDGMENT}

    def _on_step_advance(step_key: str) -> None:
        last_stage["value"] = _ENRICH_STEP_TO_ARTICLE_STAGE[step_key]
        _advance_stage(step_key)

    enrichment_run = enrich_article(
        database_url=database_url,
        article_id=claimed_run.article_id,
        enricher=enricher,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        on_step_advance=_on_step_advance,
        force_reenrich=bool(
            existing_run is not None
            and existing_run.status in ("manual_retry_requested", "running_manual_retry")
        ),
    )
    if enrichment_run.status == "skipped_advertisement":
        return succeed_article_processing_run(
            database_url=database_url,
            article_key=article_key,
            last_success_input_hash=enrichment_run.input_hash,
            current_step=ARTICLE_STAGE_ADVERTISEMENT,
        )
    if enrichment_run.status == "succeeded":
        return succeed_article_processing_run(
            database_url=database_url,
            article_key=article_key,
            last_success_input_hash=enrichment_run.input_hash,
            current_step=ARTICLE_STAGE_COMPLETED,
        )

    return fail_article_processing_run(
        database_url=database_url,
        article_key=article_key,
        failed_step=last_stage["value"],
        error_message=enrichment_run.error_message
        or f"article enrichment ended with status {enrichment_run.status}",
        automatic_failure_limit=automatic_failure_limit,
    )
```

In `enrich_document_articles` (line 1724): replace params `translator,` and `summarizer_tagger,` (lines 1728-1729) with `enricher,`, and in its `enrich_article(...)` call (lines 1744-1752) replace the `translator=translator, summarizer_tagger=summarizer_tagger,` pair with `enricher=enricher,`.

In `process_document` (line 1412): delete the now-unused params `translator=None,` and `summarizer_tagger=None,` (lines 1425-1426). They are not referenced in its body.

- [ ] **Step 4: Run the affected tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_process_article.py tests/test_process_document.py tests/test_drain.py -v`
Expected: PASS, including the Task 7 stage-transition assertions (`completed` and `classified_as_advertisement`).

- [ ] **Step 5: Commit**

```bash
git add src/newspaper_translator/document_processing.py tests/_document_processing_helpers.py tests/test_process_article.py tests/test_process_document.py tests/test_drain.py
git commit -m "feat: drive enrichment + live article stages via single enricher"
```

---

## Task 9: Config + worker + manage wiring

**Files:**
- Modify: `src/newspaper_translator/worker.py`, `src/newspaper_translator/manage.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Update the worker startup test**

In `tests/test_worker.py` (lines ~199-245): replace the two patches `DeepSeekArticleTranslator` / `DeepSeekArticleSummarizerTagger` with a single `with patch("newspaper_translator.worker.DeepSeekArticleEnricher") as enricher_class:` and `enricher_class.return_value = SimpleNamespace(name="enricher")`. Replace the assertions at lines 244-245:

```python
        self.assertEqual(process_document.call_args.kwargs["enricher"].name, "enricher")
```

(remove the `summarizer_tagger` assertion).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_worker.py -v`
Expected: FAIL — `worker` has no attribute `DeepSeekArticleEnricher` / `process_document` got unexpected kwarg `translator`.

- [ ] **Step 3: Rewire `worker.py`**

In `src/newspaper_translator/worker.py`: change the import (lines 21-25) from `DeepSeekArticleSummarizerTagger, DeepSeekArticleTranslator` to `DeepSeekArticleEnricher`.

In `build_process_one_document_from_env` (after line 194 where `step_retry_limit` is read), add:

```python
    enrichment_step_retry_limit = _read_int_setting(
        env,
        "ENRICHMENT_STEP_RETRY_LIMIT",
        default=2,
    )
```

Replace the two construction lines (207-208) with:

```python
    enricher = DeepSeekArticleEnricher(
        settings=deepseek_settings,
        step_retry_limit=enrichment_step_retry_limit,
    )
```

In the `process_document(...)` call (lines 222-223) replace `translator=translator, summarizer_tagger=summarizer_tagger,` with `enricher=enricher,`.

In `build_process_one_article_from_env`: add the same `enrichment_step_retry_limit` read after line 259, replace lines 269-270 with the `enricher = DeepSeekArticleEnricher(settings=deepseek_settings, step_retry_limit=enrichment_step_retry_limit)` construction, and in the `process_article_processing_run(...)` call (lines 277-278) replace `translator=translator, summarizer_tagger=summarizer_tagger,` with `enricher=enricher,`.

- [ ] **Step 4: Rewire `manage.py`**

In `src/newspaper_translator/manage.py`: change the import (lines 27-30) from `DeepSeekArticleSummarizerTagger, DeepSeekArticleTranslator` to `DeepSeekArticleEnricher`. Replace the phase3 enrich block (lines 257-268) with:

```python
    if args.command == "phase3-enrich-article":
        deepseek_settings = DeepSeekSettings.from_env(os.environ)
        enrichment_run = enrich_article(
            database_url=_resolve_setting(args.database_url, "DATABASE_URL"),
            article_id=args.article_id,
            enricher=DeepSeekArticleEnricher(
                settings=deepseek_settings,
                step_retry_limit=_read_int_setting(
                    os.environ, "ENRICHMENT_STEP_RETRY_LIMIT", default=2
                ),
            ),
            provider_name="deepseek",
            model_name=deepseek_settings.model,
            prompt_version="article-enrichment-v2",
        )
        return 0, json.dumps(_to_jsonable(enrichment_run), sort_keys=True)
```

If `_read_int_setting` is not already imported in `manage.py`, import it: `from newspaper_translator.config import _read_int_setting` is private; instead add a tiny local read using `os.environ.get`. Concretely, if no helper is available, replace the `step_retry_limit=...` argument with:

```python
                step_retry_limit=int(os.environ.get("ENRICHMENT_STEP_RETRY_LIMIT", "2")),
```

- [ ] **Step 5: Run worker + manage tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_worker.py tests/test_manage.py -v`
Expected: PASS.

- [ ] **Step 6: Document the new env var**

Add to `.env.example` a line documenting the new variable:

```
ENRICHMENT_STEP_RETRY_LIMIT=2
```

- [ ] **Step 7: Commit**

```bash
git add src/newspaper_translator/worker.py src/newspaper_translator/manage.py .env.example tests/test_worker.py
git commit -m "feat: wire DeepSeekArticleEnricher and ENRICHMENT_STEP_RETRY_LIMIT"
```

---

## Task 10: Frontend stage labels

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Add a stage label map and apply it at article render sites**

In `frontend/app.js`, add near the top (after the element lookups, before the first render function):

```javascript
const ARTICLE_STAGE_LABELS = {
  await_ad_judgment: "等待广告判断",
  await_translation: "等待翻译",
  await_summary: "等待摘要",
  await_tagging: "等待标签",
  completed: "完成",
  classified_as_advertisement: "判定为广告",
};

function articleStageLabel(step) {
  return ARTICLE_STAGE_LABELS[step] || step || "";
}
```

In `renderSelectOptions` (line 211), add an optional label function parameter and use it:

```javascript
function renderSelectOptions(selectElement, options, emptyLabel, labelFn) {
```

and change `option.textContent = optionValue;` (line 222) to:

```javascript
    option.textContent = labelFn ? labelFn(optionValue) : optionValue;
```

Update the article-processing step filter call (line 299) to:

```javascript
  renderSelectOptions(articleProcessingStepFilter, payload.steps, "全部阶段", articleStageLabel);
```

In `renderArticleProcessingList` (function at line 483), change line 497 from
`node.querySelector(".document-card-step").textContent = run.current_step;` to
`node.querySelector(".document-card-step").textContent = articleStageLabel(run.current_step);`

In `showArticleProcessingDetail` (function at line 535), change line 543 to use the label:
`` `状态 ${run.status} · 当前步骤 ${articleStageLabel(run.current_step)}`; ``
and the badge at line 549 to `` `step:${articleStageLabel(run.current_step)}`, ``.

Leave the document-processing render sites (lines 421/430 and 867/872) unchanged — those are document stages, out of scope.

- [ ] **Step 2: Manual verification**

Run the app per the project's run instructions and confirm an article in flight shows 等待翻译/等待摘要 etc., a finished one shows 完成, and an ad shows 判定为广告. (No automated JS tests in this repo.)

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat: render Chinese labels for article enrichment stages"
```

---

## Task 11: Full suite green + cleanup sweep

**Files:**
- Verify only (no new code unless a gap is found).

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. If any test still imports `DeepSeekArticleTranslator`, `DeepSeekArticleSummarizerTagger`, `GeminiArticleTranslator`, `GeminiArticleSummarizerTagger`, `ArticleTranslationResult`, or `ArticleSummaryTagResult`, update it the same way (single `enricher` / `EnrichmentResult`).

- [ ] **Step 2: Grep for stragglers**

Run:
```bash
grep -rn "ArticleTranslator\|ArticleSummarizerTagger\|ArticleTranslationResult\|ArticleSummaryTagResult\|summarizer_tagger" src/ tests/
```
Expected: no matches. Fix any that remain.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "test: finish multi-round enrichment migration sweep"
```

---

## Self-review notes (for the implementer)

- **Retry budget:** `step_retry_limit=2` → 3 attempts per step (`range(step_retry_limit + 1)`). Network (`OSError`/`URLError`) and format (`LlmProviderError`/`EnrichmentFormatError`) failures both retry from the last committed state; a failed attempt never appends an assistant turn.
- **Partial mapping:** translation success + summary fail → enrichment `partial`, article run `failed_retryable` resting at `await_summary`; summary success + tagging fail → `partial` resting at `await_tagging`. This preserves the existing "partial counts as a retryable failure" behavior at the article-processing layer.
- **Stage on failure:** `last_stage["value"]` tracks the furthest step entered, which equals the failure point, so `fail_article_processing_run(failed_step=...)` lands the correct resting stage without an extra DB read.
- **Out of scope:** document-level `current_step`, the `article_enrichment_*` schema, and reading-layer queries are unchanged.
