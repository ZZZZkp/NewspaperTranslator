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
