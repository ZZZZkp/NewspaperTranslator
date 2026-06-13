import json

from newspaper_translator.config import DeepSeekSettings
from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher
from newspaper_translator.llm import (
    ChatCompletionSettings,
    ChatJsonClient,
    LlmProviderError,
    Transport,
)
from newspaper_translator.pdf import ArticleFragment


class DeepSeekError(LlmProviderError):
    """Raised when DeepSeek returns an invalid response."""


def _chat_settings_from_deepseek(settings: DeepSeekSettings) -> ChatCompletionSettings:
    return ChatCompletionSettings(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
    )


class DeepSeekContinuationMatcher:
    def __init__(
        self,
        *,
        settings: DeepSeekSettings,
        transport: Transport | None = None,
    ) -> None:
        self._client = ChatJsonClient(
            settings=_chat_settings_from_deepseek(settings),
            transport=transport,
        )

    def __call__(self, fragments: list[ArticleFragment]) -> list[tuple[int, int]]:
        if not fragments:
            return []
        try:
            payload = self._client.complete_json(self._build_prompt(fragments))
            matches = payload["matches"]
        except LlmProviderError as exc:
            raise DeepSeekError(str(exc)) from exc
        except KeyError as exc:
            raise DeepSeekError("DeepSeek response did not contain a valid matches payload") from exc
        if not isinstance(matches, list):
            raise DeepSeekError("DeepSeek matches payload must be a list")

        parsed_matches: list[tuple[int, int]] = []
        for match in matches:
            if not isinstance(match, dict):
                raise DeepSeekError("DeepSeek match entry must be an object")
            front_source_order = match.get("front_source_order")
            back_source_order = match.get("back_source_order")
            if not isinstance(front_source_order, int) or not isinstance(back_source_order, int):
                raise DeepSeekError("DeepSeek match entry must include integer source orders")
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
