import json

from newspaper_translator.article_store import StoredFinalArticle
from newspaper_translator.config import DeepSeekSettings
from newspaper_translator.gemini import (
    ArticleSummaryTagResult,
    ArticleTranslationResult,
)
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


class DeepSeekArticleTranslator:
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

    def __call__(self, article: StoredFinalArticle) -> ArticleTranslationResult:
        try:
            result = self._client.complete_json(self._build_prompt(article))
            content_type = result["content_type"]
            classification_reason = result["classification_reason"]
            translated_title_zh = result["translated_title_zh"]
            translated_body_zh = result["translated_body_zh"]
        except LlmProviderError as exc:
            raise DeepSeekError(str(exc)) from exc
        except KeyError as exc:
            raise DeepSeekError("DeepSeek response did not contain a valid translation payload") from exc

        if content_type not in ("article", "advertisement", "uncertain"):
            raise DeepSeekError(
                f"DeepSeek translation payload has unsupported content_type: {content_type!r}"
            )
        if not isinstance(classification_reason, str):
            raise DeepSeekError("DeepSeek translation payload classification_reason must be a string")
        if not isinstance(translated_title_zh, str) or not isinstance(translated_body_zh, str):
            raise DeepSeekError("DeepSeek translation payload must include string title and body fields")
        if content_type in ("article", "uncertain"):
            if not translated_title_zh.strip() or not translated_body_zh.strip():
                raise DeepSeekError(
                    "DeepSeek translation payload must include translated_title_zh and translated_body_zh"
                )

        return ArticleTranslationResult(
            content_type=content_type,
            classification_reason=classification_reason.strip(),
            translated_title_zh=translated_title_zh.strip(),
            translated_body_zh=translated_body_zh.strip(),
        )

    def _build_prompt(self, article: StoredFinalArticle) -> str:
        return (
            "You are translating English newspaper content into Simplified Chinese AND classifying it. "
            "The source text is parsed from a printed newspaper page. "
            "Most parsed items are normal newspaper content and must be classified as \"article\". "
            "Only classify content as \"advertisement\" when it is very obviously a newspaper "
            "advertisement, sponsored or promotional block, subscription offer, display ad, or "
            "advertorial block. Business news, market coverage, product reporting, reviews, opinion "
            "columns, book reviews, real-estate reporting, job-market reporting, and company profiles "
            "are NOT advertisements just because they mention companies, products, prices, or services. "
            "When you are not sure, classify as \"uncertain\" and still provide the translation. "
            "return JSON only. "
            "Do not use Markdown code fences. "
            "Do not include explanations outside the JSON. "
            'Return exactly these fields: '
            '{"content_type":"article|advertisement|uncertain",'
            '"classification_reason":"...",'
            '"translated_title_zh":"...",'
            '"translated_body_zh":"..."}. '
            "For \"article\" or \"uncertain\", translated_title_zh and translated_body_zh must be non-empty. "
            "For \"advertisement\", translated_title_zh and translated_body_zh may be empty strings. "
            "Preserve continuation markers and jump words exactly when they appear in the source, "
            'such as "Please turn to page A7" or "Continued from Page One". '
            "Do not silently remove, summarize, or normalize those navigation markers. "
            "Preserve meaning rather than literal word order.\n\n"
            f"Title:\n{article.title_en}\n\n"
            f"Body:\n{article.body_text_en}\n"
        )


class DeepSeekArticleSummarizerTagger:
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

    def __call__(
        self,
        *,
        article: StoredFinalArticle,
        translated_title_zh: str,
        translated_body_zh: str,
    ) -> ArticleSummaryTagResult:
        try:
            result = self._client.complete_json(
                self._build_prompt(
                    article=article,
                    translated_title_zh=translated_title_zh,
                    translated_body_zh=translated_body_zh,
                )
            )
            summary_zh = result["summary_zh"]
            raw_tags = result["tags"]
        except LlmProviderError as exc:
            raise DeepSeekError(str(exc)) from exc
        except KeyError as exc:
            raise DeepSeekError("DeepSeek response did not contain a valid summary and tags payload") from exc

        if not isinstance(summary_zh, str) or not summary_zh.strip():
            raise DeepSeekError("DeepSeek summary payload must include summary_zh")
        if "\n" in summary_zh or "\r" in summary_zh:
            raise DeepSeekError("DeepSeek summary payload must be a single paragraph")
        normalized_tags = _normalize_tags(raw_tags)
        if not 3 <= len(normalized_tags) <= 8:
            raise DeepSeekError("DeepSeek tags payload must include 3 to 8 non-empty tags")

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
        raise DeepSeekError("DeepSeek tags payload must be a list")

    normalized_tags: list[str] = []
    seen_tags: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            raise DeepSeekError("DeepSeek tags payload entries must be strings")
        normalized_tag = raw_tag.strip()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        normalized_tags.append(normalized_tag)
        seen_tags.add(normalized_tag)
    return normalized_tags
