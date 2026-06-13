import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class _Article:
    title_en = "Big Oil Explores Farther Afield"
    body_text_en = "U.S. oil futures were trading near $90 a barrel Sunday."


class StepParsingTests(unittest.TestCase):
    def test_ad_judgment_message_includes_title_and_body(self) -> None:
        from newspaper_translator.enrichment_conversation import build_ad_judgment_message

        message = build_ad_judgment_message(_Article())
        self.assertIn("Big Oil Explores Farther Afield", message)
        self.assertIn("U.S. oil futures", message)

    def test_parse_ad_judgment_returns_type_and_reason(self) -> None:
        from newspaper_translator.enrichment_conversation import parse_ad_judgment

        self.assertEqual(
            parse_ad_judgment(
                {"content_type": "article", "classification_reason": "  normal  "}
            ),
            ("article", "normal"),
        )

    def test_parse_ad_judgment_rejects_bad_content_type(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_ad_judgment,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_ad_judgment({"content_type": "bogus", "classification_reason": ""})

    def test_parse_translation_requires_nonempty_for_article(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_translation,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_translation(
                {"translated_title_zh": "", "translated_body_zh": ""},
                content_type="article",
            )

    def test_parse_translation_allows_empty_for_advertisement(self) -> None:
        from newspaper_translator.enrichment_conversation import parse_translation

        self.assertEqual(
            parse_translation(
                {"translated_title_zh": "", "translated_body_zh": ""},
                content_type="advertisement",
            ),
            ("", ""),
        )

    def test_parse_summary_rejects_multiline(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_summary,
        )

        with self.assertRaises(EnrichmentFormatError):
            parse_summary({"summary_zh": "line one\nline two"})

    def test_parse_tags_normalizes_and_enforces_count(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            parse_tags,
        )

        self.assertEqual(
            parse_tags({"tags": ["  经济  ", "经济", "市场", "企业"]}),
            ["经济", "市场", "企业"],
        )
        with self.assertRaises(EnrichmentFormatError):
            parse_tags({"tags": ["a", "b"]})


import json as _json


def _chat_text(obj) -> str:
    return _json.dumps(obj)


class _ScriptedSend:
    """Returns queued raw texts; an entry that is an Exception is raised instead."""

    def __init__(self, outputs) -> None:
        self._outputs = list(outputs)
        self.sent_messages = []

    def __call__(self, messages):
        self.sent_messages.append(list(messages))
        nxt = self._outputs.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


class MultiRoundArticleEnricherTests(unittest.TestCase):
    def _all_ok_outputs(self):
        return [
            _chat_text({"content_type": "article", "classification_reason": "normal"}),
            _chat_text({"translated_title_zh": "标题", "translated_body_zh": "正文"}),
            _chat_text({"summary_zh": "一段摘要。"}),
            _chat_text({"tags": ["经济", "市场", "企业"]}),
        ]

    def test_runs_four_steps_and_accumulates_history(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        send = _ScriptedSend(self._all_ok_outputs())
        stages = []
        result = MultiRoundArticleEnricher(send=send)(
            _Article(), on_step_advance=stages.append
        )

        self.assertEqual(
            stages, ["ad_judgment", "translation", "summary", "tagging"]
        )
        self.assertEqual(result.translation_status, "succeeded")
        self.assertEqual(result.summary_status, "succeeded")
        self.assertEqual(result.tagging_status, "succeeded")
        self.assertEqual(result.translated_title_zh, "标题")
        self.assertEqual(result.summary_zh, "一段摘要。")
        self.assertEqual(result.tags, ["经济", "市场", "企业"])
        self.assertIsNone(result.failed_step)
        # Last send carried the whole history: u,a,u,a,u,a,u (7 messages).
        self.assertEqual(len(send.sent_messages[-1]), 7)
        self.assertEqual(send.sent_messages[-1][0]["role"], "user")
        self.assertEqual(send.sent_messages[-1][1]["role"], "assistant")

    def test_advertisement_short_circuits_after_step_one(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        send = _ScriptedSend(
            [_chat_text({"content_type": "advertisement", "classification_reason": "ad"})]
        )
        result = MultiRoundArticleEnricher(send=send)(_Article())

        self.assertEqual(result.content_type, "advertisement")
        self.assertEqual(result.translation_status, "skipped")
        self.assertEqual(result.summary_status, "skipped")
        self.assertEqual(result.tagging_status, "skipped")
        self.assertIsNone(result.failed_step)
        self.assertEqual(len(send.sent_messages), 1)

    def test_retries_a_failed_step_from_last_success(self) -> None:
        from newspaper_translator.enrichment_conversation import (
            EnrichmentFormatError,
            MultiRoundArticleEnricher,
        )

        outputs = [
            _chat_text({"content_type": "article", "classification_reason": "normal"}),
            EnrichmentFormatError("bad json"),  # translation attempt 1 fails
            _chat_text({"translated_title_zh": "标题", "translated_body_zh": "正文"}),  # attempt 2 ok
            _chat_text({"summary_zh": "一段摘要。"}),
            _chat_text({"tags": ["经济", "市场", "企业"]}),
        ]
        send = _ScriptedSend(outputs)
        result = MultiRoundArticleEnricher(send=send, step_retry_limit=2)(_Article())

        self.assertEqual(result.translation_status, "succeeded")
        # The retried translation attempt restarted from the 2-message committed history.
        self.assertEqual(len(send.sent_messages[1]), 3)  # u,a,u
        self.assertEqual(len(send.sent_messages[2]), 3)  # retry uses same committed base

    def test_exhausts_retries_and_marks_summary_partial(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        outputs = [
            _chat_text({"content_type": "article", "classification_reason": "normal"}),
            _chat_text({"translated_title_zh": "标题", "translated_body_zh": "正文"}),
            OSError("timeout"),  # summary attempt 1
            OSError("timeout"),  # summary attempt 2 (retry 1)
            OSError("timeout"),  # summary attempt 3 (retry 2)
        ]
        send = _ScriptedSend(outputs)
        result = MultiRoundArticleEnricher(send=send, step_retry_limit=2)(_Article())

        self.assertEqual(result.translation_status, "succeeded")
        self.assertEqual(result.summary_status, "failed")
        self.assertEqual(result.tagging_status, "failed")
        self.assertEqual(result.failed_step, "summary")
        self.assertIn("timeout", result.error_message)
        self.assertEqual(result.translated_title_zh, "标题")
        self.assertIsNone(result.summary_zh)

    def test_ad_judgment_failure_marks_everything_failed(self) -> None:
        from newspaper_translator.enrichment_conversation import MultiRoundArticleEnricher

        send = _ScriptedSend([OSError("net"), OSError("net"), OSError("net")])
        result = MultiRoundArticleEnricher(send=send, step_retry_limit=2)(_Article())

        self.assertIsNone(result.content_type)
        self.assertEqual(result.failed_step, "ad_judgment")
        self.assertEqual(result.translation_status, "skipped")


if __name__ == "__main__":
    unittest.main()
