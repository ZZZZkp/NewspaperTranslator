import pathlib
import sqlite3
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.article_enrichment import enrich_article
    from newspaper_translator.article_store import (
        create_parse_run,
        finalize_parse_run,
        get_latest_article_enrichment,
        list_parse_run_final_articles,
        record_parse_run_result,
    )
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.enrichment_conversation import EnrichmentResult
    from newspaper_translator.pdf import (
        ArticleFragment,
        ArticleSource,
        ParseMatchDecision,
        ParseResult,
        ParsedArticle,
    )
except ImportError:
    enrich_article = None
    create_parse_run = None
    finalize_parse_run = None
    get_latest_article_enrichment = None
    list_parse_run_final_articles = None
    record_parse_run_result = None
    run_pending_migrations = None
    EnrichmentResult = None
    ArticleFragment = None
    ArticleSource = None
    ParseMatchDecision = None
    ParseResult = None
    ParsedArticle = None


class ArticleEnrichmentTests(unittest.TestCase):
    def test_translator_receives_article_body_without_local_image_links(self) -> None:
        self.assertIsNotNone(enrich_article)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_suffix=(
                        "The oil companies want to maximize their production.\n"
                        "![](/tmp/mineru-output/images/oil-map.jpg)\n"
                        "/tmp/mineru-output/images/oil-chart.png"
                    ),
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]
            capturing = _CapturingEnricher()

            enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                enricher=capturing,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )

        self.assertIsNotNone(capturing.article)
        self.assertNotIn("oil-map.jpg", capturing.article.body_text_en)
        self.assertNotIn("oil-chart.png", capturing.article.body_text_en)
        self.assertIn("The oil companies want to maximize their production.", capturing.article.body_text_en)

    def test_persists_a_succeeded_enrichment_run(self) -> None:
        self.assertIsNotNone(enrich_article)
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_latest_article_enrichment)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_suffix="The oil companies want to maximize their production.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                enricher=_FakeEnricher(),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )
            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(run.article_id, article.article_id)
        self.assertEqual(run.parse_run_id, parse_run.parse_run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(latest_enrichment.enrichment_run_id, run.enrichment_run_id)
        self.assertEqual(latest_enrichment.status, "succeeded")
        self.assertEqual(latest_enrichment.translation_status, "succeeded")
        self.assertEqual(latest_enrichment.summary_status, "succeeded")
        self.assertEqual(latest_enrichment.tagging_status, "succeeded")
        self.assertEqual(
            latest_enrichment.translated_title_zh,
            "大型石油公司远赴他处避开中东动荡",
        )
        self.assertEqual(
            latest_enrichment.summary_zh,
            "油企为避开中东风险，正把勘探重点转向非洲和南美。",
        )
        self.assertEqual(
            latest_enrichment.tags,
            ["能源", "石油", "中东局势"],
        )

    def test_marks_translation_only_success_as_partial_when_summary_stage_fails(self) -> None:
        self.assertIsNotNone(enrich_article)
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_latest_article_enrichment)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_suffix="The oil companies want to maximize their production.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                enricher=_FailingSummaryEnricher("summary timeout"),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )
            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(run.status, "partial")
        self.assertEqual(run.error_message, "summary timeout")
        self.assertEqual(latest_enrichment.enrichment_run_id, run.enrichment_run_id)
        self.assertEqual(latest_enrichment.status, "partial")
        self.assertEqual(latest_enrichment.translation_status, "succeeded")
        self.assertEqual(latest_enrichment.summary_status, "failed")
        self.assertEqual(latest_enrichment.tagging_status, "failed")
        self.assertEqual(
            latest_enrichment.translated_title_zh,
            "大型石油公司远赴他处避开中东动荡",
        )
        self.assertEqual(latest_enrichment.summary_zh, None)
        self.assertEqual(latest_enrichment.tags, [])

    def test_marks_translation_failure_as_failed(self) -> None:
        self.assertIsNotNone(enrich_article)
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_latest_article_enrichment)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_suffix="The oil companies want to maximize their production.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                enricher=_FailingTranslationEnricher("translation timeout"),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )

            with self.assertRaises(LookupError):
                get_latest_article_enrichment(
                    database_url=database_url,
                    article_id=article.article_id,
                )

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "translation timeout")

    def test_reuses_existing_successful_enrichment_for_unchanged_article_input(self) -> None:
        self.assertIsNotNone(enrich_article)
        self.assertIsNotNone(run_pending_migrations)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )

            first_parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            parse_result = self._build_parse_result(
                title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                body_suffix="The oil companies want to maximize their production.",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=first_parse_run.parse_run_id,
                parse_result=parse_result,
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=first_parse_run.parse_run_id,
                status="succeeded",
            )
            first_article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=first_parse_run.parse_run_id,
            )[0]
            enricher = _CountingEnricher()

            first_run = enrich_article(
                database_url=database_url,
                article_id=first_article.article_id,
                enricher=enricher,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )

            second_parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=second_parse_run.parse_run_id,
                parse_result=parse_result,
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=second_parse_run.parse_run_id,
                status="succeeded",
            )
            second_article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=second_parse_run.parse_run_id,
            )[0]

            second_run = enrich_article(
                database_url=database_url,
                article_id=second_article.article_id,
                enricher=enricher,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v1",
            )

            connection = sqlite3.connect(database_path)
            try:
                enrichment_run_count = connection.execute(
                    "SELECT COUNT(*) FROM article_enrichment_runs"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(first_article.article_key, second_article.article_key)
        self.assertNotEqual(first_article.article_id, second_article.article_id)
        self.assertEqual(second_run.enrichment_run_id, first_run.enrichment_run_id)
        self.assertEqual(enrichment_run_count, 1)
        self.assertEqual(enricher.call_count, 1)

    def test_marks_advertisement_classifications_as_skipped_advertisement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Diamond Sale Today",
                    body_suffix="50% off all jewelry, this weekend only.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                enricher=_AdvertisementEnricher(),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
            )
            latest = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(run.status, "skipped_advertisement")
        self.assertEqual(latest.content_type, "advertisement")
        self.assertEqual(latest.translation_status, "skipped")
        self.assertEqual(latest.summary_status, "skipped")
        self.assertEqual(latest.tagging_status, "skipped")
        self.assertEqual(latest.tags, [])

    def test_uncertain_classifications_continue_with_summary_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Borderline Headline",
                    body_suffix="Some body text.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            run = enrich_article(
                database_url=database_url,
                article_id=article.article_id,
                enricher=_UncertainEnricher(),
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
            )
            latest = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(latest.content_type, "uncertain")
        self.assertEqual(latest.translation_status, "succeeded")
        self.assertEqual(latest.summary_status, "succeeded")
        self.assertEqual(latest.tagging_status, "succeeded")

    def _insert_document(self, database_path: pathlib.Path, *, original_filename: str) -> str:
        document_key = "message-1:attachment-1:hash-1"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO documents (
                    document_key,
                    source_name,
                    source_message_id,
                    source_attachment_id,
                    sender,
                    original_filename,
                    content_hash,
                    raw_path,
                    import_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_key,
                    "gmail",
                    "message-1",
                    "attachment-1",
                    "news@example.com",
                    original_filename,
                    "hash-1",
                    "/tmp/wsj-2026-04-20.pdf",
                    "imported",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key

    def _build_parse_result(self, *, title: str, body_suffix: str) -> ParseResult:
        return ParseResult(
            fragments=[
                ArticleFragment(
                    title=title,
                    body_text="U.S. oil futures were trading near $90 a barrel Sunday.\nPlease turn to page A7",
                    source_order=1,
                    continued_to_page="A7",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Big Oil Explores Farther Out",
                    body_text=(
                        "Continued from PageOne Friday after President Trump and Iranian officials said the Strait of Hormuz had reopened.\n"
                        f"{body_suffix}"
                    ),
                    source_order=2,
                    continued_to_page="",
                    continued_from_page="PageOne",
                ),
            ],
            match_decisions=[
                ParseMatchDecision(
                    front_source_order=1,
                    back_source_order=2,
                    decision_status="accepted",
                    decision_reason="accepted continuation pair",
                    matcher_raw_response="(1, 2)",
                )
            ],
            articles=[
                ParsedArticle(
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=2,
                    title=title,
                    body_text=(
                        "U.S. oil futures were trading near $90 a barrel Sunday.\n"
                        f"{body_suffix}"
                    ),
                    source_fragments=[
                        ArticleSource(source_order=1, fragment_role="front", sequence_index=1),
                        ArticleSource(source_order=2, fragment_role="back", sequence_index=2),
                    ],
                )
            ],
        )


def _ok_result(content_type="article"):
    return EnrichmentResult(
        content_type=content_type,
        classification_reason="Regular newspaper article.",
        translation_status="succeeded",
        summary_status="succeeded",
        tagging_status="succeeded",
        translated_title_zh="大型石油公司远赴他处避开中东动荡",
        translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
        summary_zh="油企为避开中东风险，正把勘探重点转向非洲和南美。",
        tags=["能源", "石油", "中东局势"],
        failed_step=None,
        error_message=None,
    )


class _FakeEnricher:
    def __call__(self, article, *, on_step_advance=None):
        return _ok_result()


class _CountingEnricher:
    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, article, *, on_step_advance=None):
        self.call_count += 1
        return _ok_result()


class _CapturingEnricher:
    def __init__(self) -> None:
        self.article = None

    def __call__(self, article, *, on_step_advance=None):
        self.article = article
        return _ok_result()


class _FailingTranslationEnricher:
    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, article, *, on_step_advance=None):
        return EnrichmentResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translation_status="failed",
            summary_status="skipped",
            tagging_status="skipped",
            translated_title_zh=None,
            translated_body_zh=None,
            summary_zh=None,
            tags=[],
            failed_step="translation",
            error_message=self._message,
        )


class _FailingSummaryEnricher:
    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, article, *, on_step_advance=None):
        return EnrichmentResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translation_status="succeeded",
            summary_status="failed",
            tagging_status="failed",
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
            summary_zh=None,
            tags=[],
            failed_step="summary",
            error_message=self._message,
        )


class _AdvertisementEnricher:
    def __call__(self, article, *, on_step_advance=None):
        return EnrichmentResult(
            content_type="advertisement",
            classification_reason="Display ad for jewelry retailer.",
            translation_status="skipped",
            summary_status="skipped",
            tagging_status="skipped",
            translated_title_zh=None,
            translated_body_zh=None,
            summary_zh=None,
            tags=[],
            failed_step=None,
            error_message=None,
        )


class _UncertainEnricher:
    def __call__(self, article, *, on_step_advance=None):
        return _ok_result(content_type="uncertain")


if __name__ == "__main__":
    unittest.main()
