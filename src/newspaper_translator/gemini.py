from dataclasses import dataclass
import json
import ssl
from typing import Protocol
from urllib import request

import certifi

from newspaper_translator.article_store import StoredFinalArticle
from newspaper_translator.config import GeminiSettings
from newspaper_translator.pdf import ArticleFragment


class GeminiError(RuntimeError):
    """Raised when the Gemini API returns an invalid response."""


@dataclass(frozen=True)
class ArticleTranslationResult:
    translated_title_zh: str
    translated_body_zh: str


@dataclass(frozen=True)
class ArticleSummaryTagResult:
    summary_zh: str
    tags: list[str]


class _TransportResponse(Protocol):
    status_code: int
    body: bytes


class _Transport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> _TransportResponse: ...


class GeminiContinuationMatcher:
    def __init__(
        self,
        *,
        settings: GeminiSettings,
        transport: _Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _UrllibTransport()

    def __call__(self, fragments: list[ArticleFragment]) -> list[tuple[int, int]]:
        if not fragments:
            return []

        payload = _build_request_payload(
            settings=self._settings,
            prompt=self._build_prompt(fragments),
        )
        response = self._transport.request(
            method="POST",
            url=_build_generate_content_url(self._settings),
            headers=_build_request_headers(self._settings),
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._settings.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise GeminiError(f"Gemini request failed with status {response.status_code}")

        response_payload = json.loads(response.body.decode("utf-8"))
        try:
            text = response_payload["candidates"][0]["content"]["parts"][0]["text"]
            match_payload = json.loads(text)
            matches = match_payload["matches"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini response did not contain a valid matches payload") from exc

        if not isinstance(matches, list):
            raise GeminiError("Gemini matches payload must be a list")

        parsed_matches: list[tuple[int, int]] = []
        for match in matches:
            if not isinstance(match, dict):
                raise GeminiError("Gemini match entry must be an object")
            front_source_order = match.get("front_source_order")
            back_source_order = match.get("back_source_order")
            if not isinstance(front_source_order, int) or not isinstance(back_source_order, int):
                raise GeminiError("Gemini match entry must include integer source orders")
            parsed_matches.append((front_source_order, back_source_order))

        return parsed_matches

    def _build_prompt(self, fragments: list[ArticleFragment]) -> str:
        fragment_payload = []
        for fragment in fragments:
            body_excerpt = " ".join(fragment.body_text.split())
            fragment_payload.append(
                {
                    "source_order": fragment.source_order,
                    "title": fragment.title,
                    "continued_to_page": fragment.continued_to_page,
                    "continued_from_page": fragment.continued_from_page,
                    "body_excerpt": body_excerpt[:700],
                }
            )

        return (
            "You are matching split newspaper article fragments. "
            "Some fragments are front halves with continued_to_page, and some are back halves with continued_from_page. "
            "Return ONLY strict JSON with shape "
            '{"matches":[{"front_source_order":number,"back_source_order":number}]}. '
            "Do not include explanations. Only match when they are clearly the same article.\n\n"
            "Fragments:\n"
            + json.dumps(fragment_payload, ensure_ascii=False, indent=2)
        )


class GeminiArticleTranslator:
    def __init__(
        self,
        *,
        settings: GeminiSettings,
        transport: _Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _UrllibTransport()

    def __call__(self, article: StoredFinalArticle) -> ArticleTranslationResult:
        payload = _build_request_payload(
            settings=self._settings,
            prompt=self._build_prompt(article),
        )
        response = self._transport.request(
            method="POST",
            url=_build_generate_content_url(self._settings),
            headers=_build_request_headers(self._settings),
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._settings.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise GeminiError(f"Gemini request failed with status {response.status_code}")

        try:
            result = json.loads(_extract_response_text(response.body))
            translated_title_zh = result["translated_title_zh"]
            translated_body_zh = result["translated_body_zh"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini response did not contain a valid translation payload") from exc

        if not isinstance(translated_title_zh, str) or not translated_title_zh.strip():
            raise GeminiError("Gemini translation payload must include translated_title_zh")
        if not isinstance(translated_body_zh, str) or not translated_body_zh.strip():
            raise GeminiError("Gemini translation payload must include translated_body_zh")

        return ArticleTranslationResult(
            translated_title_zh=translated_title_zh.strip(),
            translated_body_zh=translated_body_zh.strip(),
        )

    def _build_prompt(self, article: StoredFinalArticle) -> str:
        return (
            "Translate this English newspaper article into Simplified Chinese. "
            "This may be a continuation fragment from a printed newspaper layout rather than a clean standalone article. "
            "return JSON only. "
            "Do not use Markdown code fences. "
            "Do not include explanations. "
            'Return exactly these fields: {"translated_title_zh":"...","translated_body_zh":"..."}. '
            "Preserve continuation markers and jump words exactly when they appear in the source, "
            'such as "Please turn to page A7" or "Continued from Page One". '
            "Do not silently remove, summarize, or normalize those navigation markers. "
            "Preserve meaning rather than literal word order.\n\n"
            f"Title:\n{article.title_en}\n\n"
            f"Body:\n{article.body_text_en}\n"
        )


class GeminiArticleSummarizerTagger:
    def __init__(
        self,
        *,
        settings: GeminiSettings,
        transport: _Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _UrllibTransport()

    def __call__(
        self,
        *,
        article: StoredFinalArticle,
        translated_title_zh: str,
        translated_body_zh: str,
    ) -> ArticleSummaryTagResult:
        payload = _build_request_payload(
            settings=self._settings,
            prompt=self._build_prompt(
                article=article,
                translated_title_zh=translated_title_zh,
                translated_body_zh=translated_body_zh,
            ),
        )
        response = self._transport.request(
            method="POST",
            url=_build_generate_content_url(self._settings),
            headers=_build_request_headers(self._settings),
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._settings.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise GeminiError(f"Gemini request failed with status {response.status_code}")

        try:
            result = json.loads(_extract_response_text(response.body))
            summary_zh = result["summary_zh"]
            tags = result["tags"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini response did not contain a valid summary and tags payload") from exc

        if not isinstance(summary_zh, str) or not summary_zh.strip():
            raise GeminiError("Gemini summary payload must include summary_zh")
        if "\n" in summary_zh or "\r" in summary_zh:
            raise GeminiError("Gemini summary payload must be a single paragraph")
        normalized_tags = _normalize_tags(tags)
        if not 3 <= len(normalized_tags) <= 8:
            raise GeminiError("Gemini tags payload must include 3 to 8 non-empty tags")

        return ArticleSummaryTagResult(
            summary_zh=summary_zh.strip(),
            tags=normalized_tags,
        )

    def _build_prompt(
        self,
        *,
        article: StoredFinalArticle,
        translated_title_zh: str,
        translated_body_zh: str,
    ) -> str:
        return (
            "Write a Simplified Chinese news-card summary and ordered Chinese tags for this article. "
            "return JSON only. "
            "Do not use Markdown code fences. "
            "Do not include explanations. "
            'Return exactly these fields: {"summary_zh":"...","tags":["...", "..."]}. '
            "summary_zh must be a single paragraph. "
            "tags must contain 3 to 8 short Chinese phrases with no leading #.\n\n"
            f"English title:\n{article.title_en}\n\n"
            f"English body:\n{article.body_text_en}\n\n"
            f"translated_title_zh:\n{translated_title_zh}\n\n"
            f"translated_body_zh:\n{translated_body_zh}\n"
        )


def _normalize_tags(raw_tags: object) -> list[str]:
    if not isinstance(raw_tags, list):
        raise GeminiError("Gemini tags payload must be a list")

    normalized_tags: list[str] = []
    seen_tags: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            raise GeminiError("Gemini tags payload entries must be strings")
        normalized_tag = raw_tag.strip()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        normalized_tags.append(normalized_tag)
        seen_tags.add(normalized_tag)
    return normalized_tags


def _extract_response_text(body: bytes) -> str:
    response_payload = json.loads(body.decode("utf-8"))
    try:
        if "candidates" in response_payload:
            return response_payload["candidates"][0]["content"]["parts"][0]["text"]
        return response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiError("Gemini response did not contain a valid text candidate") from exc


def _build_generate_content_url(settings: GeminiSettings) -> str:
    if settings.api_compat_mode == "openai_compatible":
        return f"{settings.base_url}/chat/completions"
    return f"{settings.base_url}/models/{settings.model}:generateContent"


def _build_request_headers(settings: GeminiSettings) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if settings.api_compat_mode == "openai_compatible":
        headers["Authorization"] = f"Bearer {settings.api_token}"
    else:
        headers["x-goog-api-key"] = settings.api_token
    return headers


def _build_request_payload(*, settings: GeminiSettings, prompt: str) -> dict[str, object]:
    if settings.api_compat_mode == "openai_compatible":
        return {
            "model": settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_object",
            },
        }
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }


class _UrllibTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> _TransportResponse:
        http_request = request.Request(
            url,
            data=body,
            headers=headers or {},
            method=method,
        )
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        with request.urlopen(http_request, timeout=timeout, context=ssl_context) as response:
            return type(
                "UrllibTransportResponse",
                (),
                {
                    "status_code": response.getcode(),
                    "body": response.read(),
                },
            )()
