import json
import ssl
from typing import Protocol
from urllib import request

import certifi

from newspaper_translator.config import GeminiSettings
from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher
from newspaper_translator.llm import LlmProviderError
from newspaper_translator.pdf import ArticleFragment


class GeminiError(RuntimeError):
    """Raised when the Gemini API returns an invalid response."""


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


def _extract_response_text(body: bytes) -> str:
    response_payload = json.loads(body.decode("utf-8"))
    try:
        if "candidates" in response_payload:
            return response_payload["candidates"][0]["content"]["parts"][0]["text"]
        return response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmProviderError("Gemini response did not contain a valid text candidate") from exc


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


def _build_messages_payload(
    *, settings: GeminiSettings, messages: list[dict[str, str]]
) -> dict[str, object]:
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
