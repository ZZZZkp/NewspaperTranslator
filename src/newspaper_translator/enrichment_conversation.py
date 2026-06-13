import json
from dataclasses import dataclass

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
