import json
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ChatJsonClientTests(unittest.TestCase):
    def test_posts_chat_completion_json_request_and_extracts_text(self) -> None:
        from newspaper_translator.llm import ChatCompletionSettings, ChatJsonClient

        transport = _FakeTransport(
            responses=[
                _FakeResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": "{\"ok\": true}"
                                    }
                                }
                            ]
                        }
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

        text = client.complete_json_text("Return JSON only: {\"ok\": true}")

        self.assertEqual(text, "{\"ok\": true}")
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer deepseek-key")
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual(payload["model"], "deepseek-chat")
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertIn("Return JSON only", payload["messages"][0]["content"])

    def test_raises_provider_error_for_non_success_status(self) -> None:
        from newspaper_translator.llm import ChatCompletionSettings, ChatJsonClient, LlmProviderError

        client = ChatJsonClient(
            settings=ChatCompletionSettings(
                api_key="deepseek-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                timeout_seconds=45,
            ),
            transport=_FakeTransport(
                responses=[_FakeResponse(status_code=429, body=b'{"error":"quota"}')]
            ),
        )

        with self.assertRaises(LlmProviderError):
            client.complete_json_text("Return JSON only.")

    def test_complete_json_returns_parsed_dict(self) -> None:
        from newspaper_translator.llm import ChatCompletionSettings, ChatJsonClient

        client = ChatJsonClient(
            settings=ChatCompletionSettings(
                api_key="deepseek-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                timeout_seconds=45,
            ),
            transport=_FakeTransport(
                responses=[
                    _FakeResponse(
                        status_code=200,
                        body=json.dumps(
                            {
                                "choices": [
                                    {"message": {"content": json.dumps({"matches": [{"a": 1}]})}}
                                ]
                            }
                        ).encode("utf-8"),
                    )
                ]
            ),
        )

        payload = client.complete_json("Return JSON only.")

        self.assertEqual(payload, {"matches": [{"a": 1}]})

    def test_complete_json_raises_when_response_text_is_not_json(self) -> None:
        from newspaper_translator.llm import ChatCompletionSettings, ChatJsonClient, LlmProviderError

        client = ChatJsonClient(
            settings=ChatCompletionSettings(
                api_key="deepseek-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                timeout_seconds=45,
            ),
            transport=_FakeTransport(
                responses=[
                    _FakeResponse(
                        status_code=200,
                        body=json.dumps(
                            {"choices": [{"message": {"content": "not json"}}]}
                        ).encode("utf-8"),
                    )
                ]
            ),
        )

        with self.assertRaises(LlmProviderError):
            client.complete_json("Return JSON only.")

    def test_complete_json_text_raises_when_choices_missing(self) -> None:
        from newspaper_translator.llm import ChatCompletionSettings, ChatJsonClient, LlmProviderError

        client = ChatJsonClient(
            settings=ChatCompletionSettings(
                api_key="deepseek-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                timeout_seconds=45,
            ),
            transport=_FakeTransport(
                responses=[_FakeResponse(status_code=200, body=b"{}")]
            ),
        )

        with self.assertRaises(LlmProviderError):
            client.complete_json_text("Return JSON only.")

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


def _chat_response(content_obj) -> "_FakeResponse":
    return _FakeResponse(
        status_code=200,
        body=json.dumps({"choices": [{"message": {"content": json.dumps(content_obj)}}]}).encode("utf-8"),
    )


def _deepseek_settings():
    from newspaper_translator.config import DeepSeekSettings
    return DeepSeekSettings(
        api_key="deepseek-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=45,
    )


def _stored_article():
    from newspaper_translator.article_store import StoredFinalArticle
    return StoredFinalArticle(
        article_id="article-1",
        article_key="article-key-1",
        parse_run_id="parse-run-1",
        document_key="document-1",
        publication_date="2026-06-05",
        article_order=1,
        primary_source_order=1,
        source_fragment_count=1,
        title_en="Title",
        body_text_en="Body",
        source_page_numbers=[1],
        created_at="",
    )


class DeepSeekClientTests(unittest.TestCase):
    def test_continuation_matcher_returns_source_order_pairs(self) -> None:
        from newspaper_translator.config import DeepSeekSettings
        from newspaper_translator.deepseek import DeepSeekContinuationMatcher
        from newspaper_translator.pdf import ArticleFragment

        matcher = DeepSeekContinuationMatcher(
            settings=DeepSeekSettings(
                api_key="deepseek-key",
                base_url="https://api.deepseek.com",
                model="deepseek-chat",
                timeout_seconds=45,
            ),
            transport=_FakeTransport(
                responses=[
                    _FakeResponse(
                        status_code=200,
                        body=json.dumps(
                            {
                                "choices": [
                                    {
                                        "message": {
                                            "content": json.dumps(
                                                {
                                                    "matches": [
                                                        {
                                                            "front_source_order": 1,
                                                            "back_source_order": 2,
                                                        }
                                                    ]
                                                }
                                            )
                                        }
                                    }
                                ]
                            }
                        ).encode("utf-8"),
                    )
                ]
            ),
        )

        matches = matcher(
            [
                ArticleFragment(
                    title="Front",
                    body_text="Please turn to page A7",
                    source_order=1,
                    continued_to_page="A7",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Back",
                    body_text="Continued from PageOne",
                    source_order=2,
                    continued_to_page="",
                    continued_from_page="PageOne",
                ),
            ]
        )

        self.assertEqual(matches, [(1, 2)])

    def test_continuation_matcher_returns_empty_for_no_fragments(self) -> None:
        from newspaper_translator.deepseek import DeepSeekContinuationMatcher

        matcher = DeepSeekContinuationMatcher(
            settings=_deepseek_settings(),
            transport=_FakeTransport(responses=[]),
        )

        self.assertEqual(matcher([]), [])

    def test_continuation_matcher_raises_when_matches_not_a_list(self) -> None:
        from newspaper_translator.deepseek import DeepSeekContinuationMatcher, DeepSeekError
        from newspaper_translator.pdf import ArticleFragment

        matcher = DeepSeekContinuationMatcher(
            settings=_deepseek_settings(),
            transport=_FakeTransport(responses=[_chat_response({"matches": "nope"})]),
        )

        with self.assertRaises(DeepSeekError):
            matcher(
                [
                    ArticleFragment(
                        title="Front",
                        body_text="Please turn to page A7",
                        source_order=1,
                        continued_to_page="A7",
                        continued_from_page="",
                    ),
                ]
            )

    def test_continuation_matcher_raises_when_source_order_not_int(self) -> None:
        from newspaper_translator.deepseek import DeepSeekContinuationMatcher, DeepSeekError
        from newspaper_translator.pdf import ArticleFragment

        matcher = DeepSeekContinuationMatcher(
            settings=_deepseek_settings(),
            transport=_FakeTransport(
                responses=[
                    _chat_response(
                        {"matches": [{"front_source_order": "1", "back_source_order": 2}]}
                    )
                ]
            ),
        )

        with self.assertRaises(DeepSeekError):
            matcher(
                [
                    ArticleFragment(
                        title="Front",
                        body_text="Body",
                        source_order=1,
                        continued_to_page="A7",
                        continued_from_page="",
                    ),
                ]
            )


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


class _FakeResponse:
    def __init__(self, *, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


class _FakeTransport:
    def __init__(self, *, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, *, method, url, headers=None, body=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": body,
                "timeout": timeout,
            }
        )
        return self._responses.pop(0)


if __name__ == "__main__":
    unittest.main()
