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
        GeminiArticleTranslator,
        GeminiArticleSummarizerTagger,
        GeminiContinuationMatcher,
        GeminiError,
    )
    from newspaper_translator.pdf import ArticleFragment
    from newspaper_translator.article_store import StoredFinalArticle
except ImportError:
    GeminiSettings = None
    GeminiArticleTranslator = None
    GeminiArticleSummarizerTagger = None
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


class GeminiArticleTranslatorTests(unittest.TestCase):
    def test_builds_strict_generate_content_request_for_article_translation(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiArticleTranslator)
        self.assertIsNotNone(StoredFinalArticle)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "translated_title_zh": "大型石油公司远赴他处避开中东动荡",
                                            "translated_body_zh": "多家能源企业正加速在非洲和南美寻找新机会。",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        result = translator(
            StoredFinalArticle(
                article_id="article-1",
                parse_run_id="parse-run-1",
                document_key="message-1:attachment-1:hash-1",
                publication_date="2026-04-20",
                article_order=1,
                primary_source_order=1,
                source_fragment_count=2,
                title_en="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                body_text_en=(
                    "Exxon, Chevron and others turn to Africa and South America for next prospects.\n"
                    "Please turn to page A7"
                ),
                created_at="2026-04-28 00:00:00",
            )
        )

        self.assertEqual(result.translated_title_zh, "大型石油公司远赴他处避开中东动荡")
        self.assertEqual(
            result.translated_body_zh,
            "多家能源企业正加速在非洲和南美寻找新机会。",
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
        self.assertIn("return JSON only", prompt_text)
        self.assertIn("newspaper article", prompt_text)
        self.assertIn("continuation fragment", prompt_text)
        self.assertIn("Preserve continuation markers", prompt_text)
        self.assertIn("Please turn to page A7", prompt_text)
        self.assertIn("translated_title_zh", prompt_text)
        self.assertIn("Big Oil Explores Farther Afield To Dodge Middle East Turmoil", prompt_text)

    def test_uses_openai_compatible_chat_completions_request_for_article_translation(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiArticleTranslator)
        self.assertIsNotNone(StoredFinalArticle)

        transport = _FakeTransport(
            response_payload={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translated_title_zh": "测试标题",
                                    "translated_body_zh": "这是一段测试翻译。",
                                }
                            )
                        }
                    }
                ]
            }
        )
        translator = GeminiArticleTranslator(
            settings=GeminiSettings(
                api_token="proxy-gemini-key",
                model="gemini-2.5-flash",
                timeout_seconds=45,
                base_url="https://nuoapi.com/v1beta",
                api_compat_mode="openai_compatible",
            ),
            transport=transport,
        )

        result = translator(
            StoredFinalArticle(
                article_id="article-1",
                parse_run_id="parse-run-1",
                document_key="message-1:attachment-1:hash-1",
                publication_date="2026-04-20",
                article_order=1,
                primary_source_order=1,
                source_fragment_count=2,
                title_en="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                body_text_en="Exxon, Chevron and others turn to Africa and South America for next prospects.",
                created_at="2026-04-28 00:00:00",
            )
        )

        self.assertEqual(result.translated_title_zh, "测试标题")
        self.assertEqual(result.translated_body_zh, "这是一段测试翻译。")

        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://nuoapi.com/v1beta/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer proxy-gemini-key")

        payload = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(payload["model"], "gemini-2.5-flash")
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["response_format"]["type"], "json_object")
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertIn("return JSON only", payload["messages"][0]["content"])


class GeminiArticleSummarizerTaggerTests(unittest.TestCase):
    def test_builds_strict_generate_content_request_for_summary_and_tags(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiArticleSummarizerTagger)
        self.assertIsNotNone(StoredFinalArticle)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary_zh": "油企为避开中东风险，正把勘探重点转向非洲和南美。",
                                            "tags": ["能源", "石油", "中东局势"],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        summarizer = GeminiArticleSummarizerTagger(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        result = summarizer(
            article=StoredFinalArticle(
                article_id="article-1",
                parse_run_id="parse-run-1",
                document_key="message-1:attachment-1:hash-1",
                publication_date="2026-04-20",
                article_order=1,
                primary_source_order=1,
                source_fragment_count=2,
                title_en="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                body_text_en="Exxon, Chevron and others turn to Africa and South America for next prospects.",
                created_at="2026-04-28 00:00:00",
            ),
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
        )

        self.assertEqual(
            result.summary_zh,
            "油企为避开中东风险，正把勘探重点转向非洲和南美。",
        )
        self.assertEqual(result.tags, ["能源", "石油", "中东局势"])
        self.assertEqual(len(transport.requests), 1)

        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertIn("gemini-2.5-flash:generateContent", request["url"])
        self.assertEqual(request["headers"]["x-goog-api-key"], "gemini-token")

        payload = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["temperature"], 0)
        prompt_text = payload["contents"][0]["parts"][0]["text"]
        self.assertIn("summary_zh", prompt_text)
        self.assertIn("tags", prompt_text)
        self.assertIn("translated_title_zh", prompt_text)
        self.assertIn("大型石油公司远赴他处避开中东动荡", prompt_text)

    def test_rejects_summary_payload_with_line_breaks(self) -> None:
        self.assertIsNotNone(GeminiSettings)
        self.assertIsNotNone(GeminiArticleSummarizerTagger)
        self.assertIsNotNone(GeminiError)
        self.assertIsNotNone(StoredFinalArticle)

        transport = _FakeTransport(
            response_payload={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary_zh": "第一段摘要。\n第二段摘要。",
                                            "tags": ["能源", "石油", "中东局势"],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )
        summarizer = GeminiArticleSummarizerTagger(
            settings=GeminiSettings(api_token="gemini-token", model="gemini-2.5-flash", timeout_seconds=45),
            transport=transport,
        )

        with self.assertRaises(GeminiError):
            summarizer(
                article=StoredFinalArticle(
                    article_id="article-1",
                    parse_run_id="parse-run-1",
                    document_key="message-1:attachment-1:hash-1",
                    publication_date="2026-04-20",
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=2,
                    title_en="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text_en="Exxon, Chevron and others turn to Africa and South America for next prospects.",
                    created_at="2026-04-28 00:00:00",
                ),
                translated_title_zh="大型石油公司远赴他处避开中东动荡",
                translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
            )


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


if __name__ == "__main__":
    unittest.main()
