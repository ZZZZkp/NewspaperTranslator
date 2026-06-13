from dataclasses import dataclass
import json
import ssl
from typing import Protocol
from urllib import error as urllib_error, request

import certifi


class LlmProviderError(RuntimeError):
    """Raised when an LLM provider returns an invalid or failed response."""


@dataclass(frozen=True)
class ChatCompletionSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes


class Transport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> TransportResponse:
        ...


class ChatJsonClient:
    def __init__(
        self,
        *,
        settings: ChatCompletionSettings,
        transport: Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or UrllibTransport()

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
        try:
            response_payload = json.loads(response.body.decode("utf-8"))
            text = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LlmProviderError("LLM response did not contain a valid text choice") from exc
        if not isinstance(text, str) or not text.strip():
            raise LlmProviderError("LLM response text choice was empty")
        return text.strip()

    def complete_json(self, prompt: str) -> dict[str, object]:
        text = self.complete_json_text(prompt)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LlmProviderError("LLM response text was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LlmProviderError("LLM response JSON must be an object")
        return payload


class UrllibTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ) -> TransportResponse:
        http_request = request.Request(
            url,
            data=body,
            headers=headers or {},
            method=method,
        )
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        try:
            with request.urlopen(http_request, timeout=timeout, context=ssl_context) as response:
                return TransportResponse(
                    status_code=response.getcode(),
                    body=response.read(),
                )
        except urllib_error.HTTPError as exc:
            return TransportResponse(
                status_code=exc.code,
                body=exc.read() or b"",
            )
