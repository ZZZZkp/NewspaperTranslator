import json
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.config import GeminiSettings
    from newspaper_translator.gemini import (
        GeminiContinuationMatcher,
        GeminiError,
    )
    from newspaper_translator.pdf import ArticleFragment
    from newspaper_translator.article_store import StoredFinalArticle
except ImportError:
    GeminiSettings = None
    GeminiContinuationMatcher = None
    GeminiError = None
    ArticleFragment = None
    StoredFinalArticle = None


class GeminiContinuationMatcherTests(unittest.TestCase):
    def test_returns_matches_from_gemini_json_response(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiContinuationMatcher)
        self.assertIsNotNone(ArticleFragment)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "matches": [
                                                {
                                                    "front_source_order": 2,
                                                    "back_source_order": 31,
                                                }
                                            ]
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        matcher = GeminiContinuationMatcher(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        matches = matcher(
            [
                ArticleFragment(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="Please turn to page A7",
                    source_order=2,
                    continued_to_page="A7",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Big Oil Explores Farther Out",
                    body_text="Continued from PageOne Friday after President Trump...",
                    source_order=31,
                    continued_to_page="",
                    continued_from_page="PageOne",
                ),
            ]
        )

        self.assertEqual(matches, [(2, 31)])

    def test_builds_generate_content_request_with_fragment_payload(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiContinuationMatcher)
        self.assertIsNotNone(ArticleFragment)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "{\"matches\": []}"
                                }
                            ]
                        }
                    }
                ]
            }
        )
        matcher = GeminiContinuationMatcher(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        matcher(
            [
                ArticleFragment(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="Please turn to page A7",
                    source_order=2,
                    continued_to_page="A7",
                    continued_from_page="",
                )
            ]
        )

        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertIn("gemini-2.5-flash:generateContent", request["url"])
        self.assertEqual(request["headers"]["x-goog-api-key"], "gemini-token")

        payload = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["temperature"], 0)
        prompt_text = payload["contents"][0]["parts"][0]["text"]
        self.assertIn("front_source_order", prompt_text)
        self.assertIn("Big Oil Explores Farther Afield To Dodge Middle East Turmoil", prompt_text)

    def test_uses_configured_base_url_for_fragment_matching_requests(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiContinuationMatcher)
        self.assertIsNotNone(ArticleFragment)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "{\"matches\": []}"
                                }
                            ]
                        }
                    }
                ]
            }
        )
        matcher = GeminiContinuationMatcher(
            settings=GeminiSettings(
                api_token="proxy-gemini-key",
                model="gemini-2.5-flash",
                timeout_seconds=45,
                base_url="https://nuoapi.com/v1beta",
                api_compat_mode="openai_compatible",
            ),
            transport=transport,
        )

        matcher(
            [
                ArticleFragment(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="Please turn to page A7",
                    source_order=2,
                    continued_to_page="A7",
                    continued_from_page="",
                )
            ]
        )

        request = transport.requests[0]
        self.assertEqual(
            request["url"],
            "https://nuoapi.com/v1beta/chat/completions",
        )
        payload = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(payload["model"], "gemini-2.5-flash")
        self.assertEqual(payload["messages"][0]["role"], "user")

    def test_uses_bearer_authorization_header_for_openai_compatible_requests(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiContinuationMatcher)
        self.assertIsNotNone(ArticleFragment)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "{\"matches\": []}"
                                }
                            ]
                        }
                    }
                ]
            }
        )
        matcher = GeminiContinuationMatcher(
            settings=GeminiSettings(
                api_token="proxy-gemini-key",
                model="gemini-2.5-flash",
                timeout_seconds=45,
                base_url="https://nuoapi.com/v1beta",
                api_compat_mode="openai_compatible",
            ),
            transport=transport,
        )

        matcher(
            [
                ArticleFragment(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="Please turn to page A7",
                    source_order=2,
                    continued_to_page="A7",
                    continued_from_page="",
                )
            ]
        )

        request = transport.requests[0]
        self.assertEqual(request["headers"]["Authorization"], "Bearer proxy-gemini-key")
        self.assertNotIn("x-goog-api-key", request["headers"])

    def test_returns_empty_matches_without_calling_transport_for_empty_fragments(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiContinuationMatcher)

        transport = _FakeTransport(response_payload={})
        matcher = GeminiContinuationMatcher(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        matches = matcher([])

        self.assertEqual(matches, [])
        self.assertEqual(transport.requests, [])

    def test_raises_gemini_error_for_malformed_match_payload(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiContinuationMatcher)
        self.assertIsNotNone(GeminiError)
        self.assertIsNotNone(ArticleFragment)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "{\"not_matches\": []}"
                                }
                            ]
                        }
                    }
                ]
            }
        )
        matcher = GeminiContinuationMatcher(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        with self.assertRaises(GeminiError):
            matcher(
                [
                    ArticleFragment(
                        title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                        body_text="Please turn to page A7",
                        source_order=2,
                        continued_to_page="A7",
                        continued_from_page="",
                    )
                ]
            )


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
            transport=_FakeSequenceTransport(
                response_payloads=[
                    _openai_response({"content_type": "article", "classification_reason": "normal"}),
                    _openai_response({"translated_title_zh": "标题", "translated_body_zh": "正文"}),
                    _openai_response({"summary_zh": "一段摘要。"}),
                    _openai_response({"tags": ["经济", "市场", "企业"]}),
                ]
            ),
        )

        result = enricher(
            StoredFinalArticle(
                article_id="article-1",
                parse_run_id="parse-run-1",
                document_key="message-1:attachment-1:hash-1",
                publication_date="2026-04-20",
                article_order=1,
                primary_source_order=1,
                source_fragment_count=1,
                title_en="Headline",
                body_text_en="Body.",
                created_at="2026-04-28 00:00:00",
            )
        )

        self.assertEqual(result.translated_title_zh, "标题")
        self.assertEqual(result.tags, ["经济", "市场", "企业"])
        self.assertEqual(result.tagging_status, "succeeded")


def _openai_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class _FakeTransport:
    def __init__(self, *, response_payload: dict[str, object]) -> None:
        self._response_payload = response_payload
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": body or b"",
                "timeout": timeout,
            }
        )
        return type(
            "FakeTransportResponse",
            (),
            {
                "status_code": 200,
                "body": json.dumps(self._response_payload).encode("utf-8"),
            },
        )()


class _FakeSequenceTransport:
    """Like _FakeTransport but pops responses from a list, one per call."""

    def __init__(self, *, response_payloads: list[dict[str, object]]) -> None:
        self._response_payloads = list(response_payloads)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int | None = None,
    ):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": body or b"",
                "timeout": timeout,
            }
        )
        payload = self._response_payloads.pop(0)
        return type(
            "FakeTransportResponse",
            (),
            {
                "status_code": 200,
                "body": json.dumps(payload).encode("utf-8"),
            },
        )()


if __name__ == "__main__":
    unittest.main()
