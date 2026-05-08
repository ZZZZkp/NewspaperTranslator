import pathlib
import sqlite3
import sys
import tempfile
import unittest
import uuid


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.api.queries import (
        get_article_processing_filter_options_view,
        list_article_processing_card_views,
        get_article_processing_detail_view,
        get_document_processing_detail_view,
        get_article_detail_view,
        get_filter_options_view,
        get_overview_view,
        list_article_card_views,
        list_focus_tag_article_card_views,
    )
    from newspaper_translator.article_store import (
        create_article_enrichment_run,
        create_parse_run,
        finalize_article_enrichment_run,
        finalize_parse_run,
        get_final_article,
        list_parse_run_final_articles,
        record_article_enrichment_outputs,
        record_parse_run_result,
        StoredFinalArticle,
    )
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.document_processing import (
        create_article_processing_run,
        create_document_processing_run,
    )
    from newspaper_translator.pdf import (
        ArticleFragment,
        ArticleSource,
        ParseMatchDecision,
        ParseResult,
        ParsedArticle,
    )
except ImportError:
    get_article_processing_filter_options_view = None
    list_article_processing_card_views = None
    get_article_processing_detail_view = None
    get_document_processing_detail_view = None
    get_article_detail_view = None
    get_filter_options_view = None
    get_overview_view = None
    list_article_card_views = None
    list_focus_tag_article_card_views = None
    create_article_enrichment_run = None
    create_parse_run = None
    finalize_article_enrichment_run = None
    finalize_parse_run = None
    get_final_article = None
    list_parse_run_final_articles = None
    record_article_enrichment_outputs = None
    record_parse_run_result = None
    run_pending_migrations = None
    StoredFinalArticle = None
    create_article_processing_run = None
    create_document_processing_run = None
    ArticleFragment = None
    ArticleSource = None
    ParseMatchDecision = None
    ParseResult = None
    ParsedArticle = None


class ArticleQueryTests(unittest.TestCase):
    def test_focus_tag_article_cards_return_articles_matching_any_configured_focus_tag(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_focus_tag_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            third_document_key = self._insert_document(
                database_path,
                original_filename="econ-2026-04-22.pdf",
                source_name="The Economist",
                document_key="message-3:attachment-1:hash-3",
            )

            first_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Hardware", "Trade", "Policy"],
            )
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=third_document_key,
                publication_date="2026-04-22",
                title="Cities recover commuter traffic",
                body_suffix="Urban planners are reassessing transport demand.",
                translated_title_zh="城市正在恢复通勤流量",
                summary_zh="城市规划者正在重新评估交通需求。",
                translated_body_zh="随着通勤回暖，城市交通系统正在重新分配资源。",
                tags=["Cities", "Transport", "Urbanism"],
            )

            cards = list_focus_tag_article_card_views(
                database_url=database_url,
                focus_tags=["Semiconductors", "Hardware"],
            )

        self.assertEqual([card.article_id for card in cards], [first_article_id, second_article_id])

    def test_filter_options_return_distinct_sources_and_tags(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_filter_options_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )

            first_article = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            self.assertIsNotNone(first_article)
            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Policy", "Hardware", "Trade"],
            )

            filters = get_filter_options_view(database_url=database_url)

        self.assertEqual(filters.sources, ["Financial Times", "Wall Street Journal"])
        self.assertEqual(filters.tags, ["Hardware", "Policy", "Semiconductors", "Trade"])

    def test_overview_counts_imports_articles_processing_and_pending_exceptions(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_overview_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            import_run_id = self._insert_import_run(database_path, created_document_count=2)
            doc_running = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            doc_retryable = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            doc_terminal = self._insert_document(
                database_path,
                original_filename="econ-2026-04-22.pdf",
                source_name="The Economist",
                document_key="message-3:attachment-1:hash-3",
            )

            self._insert_document_processing_run(
                database_path,
                document_key=doc_running,
                status="running",
                current_step="parse_persist",
            )
            self._insert_document_processing_run(
                database_path,
                document_key=doc_retryable,
                status="failed_retryable",
                current_step="enrich",
            )
            self._insert_document_processing_run(
                database_path,
                document_key=doc_terminal,
                status="failed_terminal",
                current_step="enrich",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=doc_running,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=doc_running,
                publication_date="2026-04-22",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )

            overview = get_overview_view(database_url=database_url)

        self.assertEqual(import_run_id is not None, True)
        self.assertEqual(overview.imported_document_count, 2)
        self.assertEqual(overview.article_count, 1)
        self.assertEqual(overview.pending_article_count, 1)
        self.assertEqual(overview.processing_document_count, 1)
        self.assertEqual(overview.pending_exception_count, 2)

    def test_article_cards_prefer_latest_usable_chinese_enrichment(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=document_key,
                publication_date="2026-04-22",
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

            enrichment_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="succeeded",
            )

            cards = list_article_card_views(database_url=database_url)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].article_id, article.article_id)
        self.assertEqual(cards[0].source_name, "Financial Times")
        self.assertEqual(cards[0].publication_date, "2026-04-22")
        self.assertEqual(cards[0].title_zh, "芯片制造商准备应对新的补贴争端")
        self.assertEqual(cards[0].summary_zh, "多国芯片企业正重新评估补贴竞争和供应链布局。")
        self.assertEqual(cards[0].tags, ["Semiconductors", "Policy", "Trade"])
        self.assertEqual(cards[0].processing_badges, [])
        self.assertEqual(cards[0].quality_flags, [])

    def test_article_cards_mark_partial_enrichment_when_latest_usable_run_is_partial(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=document_key,
                publication_date="2026-04-22",
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

            enrichment_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh=None,
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                translation_status="succeeded",
                summary_status="failed",
                tagging_status="failed",
                tags=[],
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="partial",
                error_message="summary timeout",
            )

            cards = list_article_card_views(database_url=database_url)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].title_zh, "芯片制造商准备应对新的补贴争端")
        self.assertEqual(cards[0].summary_zh, None)
        self.assertEqual(cards[0].processing_badges, ["partial_enrichment"])

    def test_article_cards_fall_back_to_english_when_no_usable_enrichment_exists(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=document_key,
                publication_date="2026-04-22",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )

            cards = list_article_card_views(database_url=database_url)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].title_en, "Chipmakers prepare for a new subsidy dispute")
        self.assertEqual(cards[0].title_zh, None)
        self.assertEqual(cards[0].summary_zh, None)
        self.assertEqual(cards[0].tags, [])
        self.assertEqual(cards[0].reading_status, "english_fallback")

    def test_article_detail_returns_bilingual_content_and_processing_context(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_article_detail_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                ),
                document_key=document_key,
                publication_date="2026-04-22",
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

            enrichment_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v2",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_run.enrichment_run_id,
                status="succeeded",
            )
            self._insert_document_processing_run(
                database_path,
                document_key=document_key,
                status="succeeded",
                current_step="completed",
            )

            detail = get_article_detail_view(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(detail.article_id, article.article_id)
        self.assertEqual(detail.source_name, "Financial Times")
        self.assertEqual(detail.title_zh, "芯片制造商准备应对新的补贴争端")
        self.assertEqual(detail.summary_zh, "多国芯片企业正重新评估补贴竞争和供应链布局。")
        self.assertIn("Subsidy pressure is spreading across Asia and Europe.", detail.body_text_en)
        self.assertEqual(detail.body_text_zh, "随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。")
        self.assertEqual(detail.tags, ["Semiconductors", "Policy", "Trade"])
        self.assertEqual(detail.processing["document_status"], "succeeded")
        self.assertEqual(detail.processing["latest_parse_status"], "succeeded")
        self.assertEqual(detail.processing["latest_enrichment_status"], "succeeded")

    def test_article_detail_returns_local_images_and_clean_body(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_article_detail_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            parse_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-22",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Chipmakers prepare for a new subsidy dispute",
                    body_suffix=(
                        "Subsidy pressure is spreading across Asia and Europe.\n"
                        "![](/tmp/mineru-output/images/chips.jpg)\n"
                        "/tmp/mineru-output/images/factory.webp"
                    ),
                ),
                document_key=document_key,
                publication_date="2026-04-22",
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

            detail = get_article_detail_view(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(
            detail.images,
            [
                "/tmp/mineru-output/images/chips.jpg",
                "/tmp/mineru-output/images/factory.webp",
            ],
        )
        self.assertIn("Subsidy pressure is spreading across Asia and Europe.", detail.body_text_en)
        self.assertNotIn("chips.jpg", detail.body_text_en)
        self.assertNotIn("factory.webp", detail.body_text_en)

    def test_document_processing_detail_includes_current_visible_articles(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_document_processing_detail_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
            )

            first_article = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            self._insert_document_processing_run(
                database_path,
                document_key=document_key,
                status="succeeded",
                current_step="completed",
            )

            detail = get_document_processing_detail_view(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(detail.document_key, document_key)
        self.assertEqual(detail.status, "succeeded")
        self.assertEqual(detail.source_name, "Financial Times")
        self.assertEqual(detail.original_filename, "ft-2026-04-22.pdf")
        self.assertEqual(detail.sender, "news@example.com")
        self.assertEqual(detail.import_status, "imported")
        self.assertEqual(detail.raw_path, "/tmp/ft-2026-04-22.pdf")
        self.assertEqual(detail.visible_article_count, 1)
        self.assertEqual(
            [article.article_id for article in detail.visible_articles],
            [first_article],
        )
        self.assertEqual(
            detail.visible_articles[0].title_zh,
            "芯片制造商准备应对新的补贴争端",
        )
        self.assertEqual(detail.visible_articles[0].reading_status, "ready")
        self.assertEqual(detail.latest_error_summary, "当前没有错误。")

    def test_document_processing_detail_surfaces_failure_summary(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_document_processing_detail_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            self._insert_document_processing_run(
                database_path,
                document_key=document_key,
                status="failed_retryable",
                current_step="enrich",
                last_failure_step="enrich",
                last_error_message="gemini quota exhausted",
            )

            detail = get_document_processing_detail_view(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual(
            detail.latest_error_summary,
            "enrich: gemini quota exhausted",
        )

    def test_article_processing_detail_view_includes_article_context_and_failure_summary(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_article_processing_detail_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            article_key = self._get_article_key(database_path=database_path, article_id=article_id)
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=article_key,
                article_id=article_id,
                status="failed_retryable",
                current_step="enrich",
                last_error_message="summary timeout",
            )

            detail = get_article_processing_detail_view(
                database_url=database_url,
                article_key=article_key,
            )

        self.assertEqual(detail.article_key, article_key)
        self.assertEqual(detail.article_id, article_id)
        self.assertEqual(detail.document_key, document_key)
        self.assertEqual(detail.source_name, "Wall Street Journal")
        self.assertEqual(detail.original_filename, "wsj-2026-04-22.pdf")
        self.assertEqual(detail.title_en, "Chipmakers prepare for a new subsidy dispute")
        self.assertEqual(detail.status, "failed_retryable")
        self.assertEqual(detail.source_page_numbers, [0])
        self.assertEqual(detail.latest_error_summary, "enrich: summary timeout")
        self.assertEqual(detail.automatic_failure_count, 0)
        self.assertIsNone(detail.last_success_input_hash)

    def test_article_processing_detail_view_exposes_advertisement_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            article = self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
                classification_reason="Display ad block.",
            )
            create_article_processing_run(
                database_url=database_url,
                article_id=article.article_id,
            )
            article_key = get_final_article(
                database_url=database_url,
                article_id=article.article_id,
            ).article_key

            view = get_article_processing_detail_view(
                database_url=database_url,
                article_key=article_key,
            )

        self.assertEqual(view.content_type, "advertisement")
        self.assertEqual(view.classification_reason, "Display ad block.")
        self.assertEqual(view.latest_enrichment_status, "skipped_advertisement")

    def test_article_processing_card_views_include_operator_context(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_processing_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            article_key = self._get_article_key(database_path=database_path, article_id=article_id)
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=article_key,
                article_id=article_id,
                status="failed_retryable",
                current_step="enrich",
                last_error_message="summary timeout",
            )

            cards = list_article_processing_card_views(
                database_url=database_url,
                page_size=20,
            )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].article_key, article_key)
        self.assertEqual(cards[0].article_id, article_id)
        self.assertEqual(cards[0].document_key, document_key)
        self.assertEqual(cards[0].title_en, "Chipmakers prepare for a new subsidy dispute")
        self.assertEqual(cards[0].source_name, "Wall Street Journal")
        self.assertEqual(cards[0].original_filename, "wsj-2026-04-22.pdf")
        self.assertEqual(cards[0].publication_date, "2026-04-22")
        self.assertEqual(cards[0].source_page_numbers, [0])
        self.assertEqual(cards[0].status, "failed_retryable")
        self.assertEqual(cards[0].current_step, "enrich")
        self.assertEqual(cards[0].automatic_failure_count, 0)
        self.assertEqual(cards[0].latest_error_summary, "enrich: summary timeout")

    def test_article_processing_card_views_support_source_and_date_filters(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_processing_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-24.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            first_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="First article",
                body_suffix="First body.",
                translated_title_zh="第一篇文章",
                summary_zh="第一篇摘要",
                translated_body_zh="第一篇正文。",
                tags=["First", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-24",
                title="Second article",
                body_suffix="Second body.",
                translated_title_zh="第二篇文章",
                summary_zh="第二篇摘要",
                translated_body_zh="第二篇正文。",
                tags=["Second", "Policy", "Trade"],
            )
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=self._get_article_key(database_path=database_path, article_id=first_article_id),
                article_id=first_article_id,
                status="pending",
                current_step="enrich",
            )
            second_article_key = self._get_article_key(database_path=database_path, article_id=second_article_id)
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=second_article_key,
                article_id=second_article_id,
                status="pending",
                current_step="enrich",
            )

            cards = list_article_processing_card_views(
                database_url=database_url,
                page_size=20,
                source="Wall Street Journal",
                publication_date_from="2026-04-23",
                publication_date_to="2026-04-24",
            )

        self.assertEqual([card.article_key for card in cards], [second_article_key])

    def test_article_processing_card_views_support_pagination_step_and_error_message(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_processing_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key_a = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-a.pdf",
                source_name="WSJ",
                document_key="message-1:attachment-1:hash-1",
            )
            document_key_b = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-b.pdf",
                source_name="WSJ",
                document_key="message-2:attachment-1:hash-2",
            )
            article_a_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key_a,
                publication_date="2026-04-22",
                title="Article A",
                body_suffix="Article A body.",
                translated_title_zh="文章A",
                summary_zh="文章A摘要",
                translated_body_zh="文章A正文。",
                tags=["Policy", "Trade", "US"],
            )
            article_b_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key_b,
                publication_date="2026-04-22",
                title="Article B",
                body_suffix="Article B body.",
                translated_title_zh="文章B",
                summary_zh="文章B摘要",
                translated_body_zh="文章B正文。",
                tags=["Policy", "Trade", "US"],
            )
            document_key_c = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-c.pdf",
                source_name="WSJ",
                document_key="message-3:attachment-1:hash-3",
            )
            article_c_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=document_key_c,
                publication_date="2026-04-22",
                title="Article C",
                body_suffix="Article C body.",
                translated_title_zh="文章C",
                summary_zh="文章C摘要",
                translated_body_zh="文章C正文。",
                tags=["Policy", "Trade", "US"],
            )
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=self._get_article_key(database_path=database_path, article_id=article_a_id),
                article_id=article_a_id,
                status="failed_retryable",
                current_step="enrich",
                last_error_message="summary timeout",
            )
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=self._get_article_key(database_path=database_path, article_id=article_b_id),
                article_id=article_b_id,
                status="failed_retryable",
                current_step="translate",
                last_error_message="quota exhausted",
            )
            article_c_key = self._get_article_key(database_path=database_path, article_id=article_c_id)
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=article_c_key,
                article_id=article_c_id,
                status="failed_retryable",
                current_step="enrich",
                last_error_message="summary timeout",
            )

            page_one, pagination = list_article_processing_card_views(
                database_url=database_url,
                page=1,
                page_size=1,
                status="failed_retryable",
                step="enrich",
                error_message="summary timeout",
                include_pagination=True,
            )
            page_two, _ = list_article_processing_card_views(
                database_url=database_url,
                page=2,
                page_size=1,
                status="failed_retryable",
                step="enrich",
                error_message="summary timeout",
                include_pagination=True,
            )

        self.assertEqual(pagination.page, 1)
        self.assertEqual(pagination.page_size, 1)
        self.assertEqual(pagination.total_count, 2)
        self.assertEqual(pagination.total_pages, 2)
        self.assertEqual([run.title_en for run in page_one], ["Article C"])
        self.assertEqual([run.title_en for run in page_two], ["Article A"])

    def test_article_processing_filter_options_follow_active_filters(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(get_article_processing_filter_options_view)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            wsj_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="WSJ",
                document_key="message-1:attachment-1:hash-1",
            )
            ft_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="FT",
                document_key="message-2:attachment-1:hash-2",
            )
            wsj_enrich_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=wsj_document_key,
                publication_date="2026-04-22",
                title="WSJ Enrich",
                body_suffix="WSJ enrich body.",
                translated_title_zh="华尔街见闻富集",
                summary_zh="摘要",
                translated_body_zh="正文。",
                tags=["Policy", "Trade", "US"],
            )
            wsj_translate_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=wsj_document_key,
                publication_date="2026-04-22",
                title="WSJ Translate",
                body_suffix="WSJ translate body.",
                translated_title_zh="华尔街见闻翻译",
                summary_zh="摘要",
                translated_body_zh="正文。",
                tags=["Policy", "Trade", "US"],
            )
            ft_enrich_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=ft_document_key,
                publication_date="2026-04-22",
                title="FT Enrich",
                body_suffix="FT enrich body.",
                translated_title_zh="金融时报富集",
                summary_zh="摘要",
                translated_body_zh="正文。",
                tags=["Policy", "Trade", "UK"],
            )
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=self._get_article_key(database_path=database_path, article_id=wsj_enrich_id),
                article_id=wsj_enrich_id,
                status="failed_retryable",
                current_step="enrich",
                last_error_message="summary timeout",
            )
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=self._get_article_key(database_path=database_path, article_id=wsj_translate_id),
                article_id=wsj_translate_id,
                status="failed_retryable",
                current_step="translate",
                last_error_message="quota exhausted",
            )
            self._insert_article_processing_run(
                database_path=database_path,
                article_key=self._get_article_key(database_path=database_path, article_id=ft_enrich_id),
                article_id=ft_enrich_id,
                status="failed_retryable",
                current_step="enrich",
                last_error_message="other source timeout",
            )

            options = get_article_processing_filter_options_view(
                database_url=database_url,
                status="failed_retryable",
                source="WSJ",
                step="enrich",
            )

        self.assertEqual(options.steps, ["enrich", "translate"])
        self.assertEqual(options.error_messages, ["summary timeout"])

    def test_article_card_views_support_pagination_reading_status_and_processing_status(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            ready_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-ready.pdf",
                source_name="Wall Street Journal",
                document_key="message-1:attachment-1:hash-1",
            )
            partial_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-partial.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )
            fallback_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-fallback.pdf",
                source_name="Wall Street Journal",
                document_key="message-3:attachment-1:hash-3",
            )
            ready_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=ready_document_key,
                publication_date="2026-04-22",
                title="Ready article",
                body_suffix="Ready article body.",
                translated_title_zh="标题一",
                summary_zh="摘要一",
                translated_body_zh="正文一。",
                tags=["Policy", "Trade", "US"],
            )
            article_partial_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=partial_document_key,
                publication_date="2026-04-22",
                title="Partial article",
                body_suffix="Partial article body.",
                translated_title_zh="标题二",
                summary_zh=None,
                translated_body_zh="正文二。",
                tags=["Policy", "Trade", "US"],
                enrichment_status="partial",
            )
            second_partial_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22-partial-2.pdf",
                source_name="Wall Street Journal",
                document_key="message-4:attachment-1:hash-4",
            )
            second_partial_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_partial_document_key,
                publication_date="2026-04-22",
                title="Second partial article",
                body_suffix="Second partial article body.",
                translated_title_zh="标题三",
                summary_zh=None,
                translated_body_zh="正文三。",
                tags=["Policy", "Trade", "US"],
                enrichment_status="partial",
            )
            self._insert_succeeded_article_without_enrichment(
                database_url=database_url,
                document_key=fallback_document_key,
                publication_date="2026-04-22",
                title="English fallback article",
                body_suffix="Fallback article body.",
            )

            page_one, pagination_one = list_article_card_views(
                database_url=database_url,
                page=1,
                page_size=1,
                reading_status="ready",
                processing_status="partial_enrichment",
                include_pagination=True,
            )
            page_two, pagination_two = list_article_card_views(
                database_url=database_url,
                page=2,
                page_size=1,
                reading_status="ready",
                processing_status="partial_enrichment",
                include_pagination=True,
            )

        self.assertEqual(pagination_one.page, 1)
        self.assertEqual(pagination_one.page_size, 1)
        self.assertEqual(pagination_one.total_count, 2)
        self.assertEqual(pagination_one.total_pages, 2)
        self.assertEqual(len(page_one), 1)
        self.assertEqual(page_one[0].article_id, second_partial_article_id)
        self.assertEqual(pagination_two.page, 2)
        self.assertEqual(len(page_two), 1)
        self.assertEqual(page_two[0].article_id, article_partial_id)
        self.assertNotEqual(ready_article_id, page_one[0].article_id)

    def test_article_cards_support_source_filter(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )

            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Policy", "Hardware", "Trade"],
            )

            cards = list_article_card_views(
                database_url=database_url,
                source="Wall Street Journal",
            )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].article_id, second_article_id)
        self.assertEqual(cards[0].source_name, "Wall Street Journal")

    def test_article_cards_support_tag_filter(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            first_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-22.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            second_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )

            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=first_document_key,
                publication_date="2026-04-22",
                title="Chipmakers prepare for a new subsidy dispute",
                body_suffix="Subsidy pressure is spreading across Asia and Europe.",
                translated_title_zh="芯片制造商准备应对新的补贴争端",
                summary_zh="多国芯片企业正重新评估补贴竞争和供应链布局。",
                translated_body_zh="随着补贴争夺升级，芯片制造商开始重新配置产能与投资方向。",
                tags=["Semiconductors", "Policy", "Trade"],
            )
            second_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=second_document_key,
                publication_date="2026-04-22",
                title="Export controls reshape hardware planning",
                body_suffix="Manufacturers are adjusting long-term procurement plans.",
                translated_title_zh="出口管制正在重塑硬件规划",
                summary_zh="硬件制造商正在根据新的出口限制重新安排采购。",
                translated_body_zh="新的出口限制正在迫使硬件公司调整长期规划与供应商结构。",
                tags=["Policy", "Hardware", "Trade"],
            )

            cards = list_article_card_views(
                database_url=database_url,
                tag="Hardware",
            )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].article_id, second_article_id)
        self.assertEqual(cards[0].tags, ["Policy", "Hardware", "Trade"])

    def test_article_cards_support_publication_date_range_filter(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            older_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-21.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            newer_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )

            self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=older_document_key,
                publication_date="2026-04-21",
                title="Older article",
                body_suffix="Older article body.",
                translated_title_zh="较早文章",
                summary_zh="较早文章摘要。",
                translated_body_zh="较早文章正文。",
                tags=["Markets", "Europe", "Trade"],
            )
            newer_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=newer_document_key,
                publication_date="2026-04-22",
                title="Newer article",
                body_suffix="Newer article body.",
                translated_title_zh="较新文章",
                summary_zh="较新文章摘要。",
                translated_body_zh="较新文章正文。",
                tags=["Policy", "Hardware", "Trade"],
            )

            cards = list_article_card_views(
                database_url=database_url,
                publication_date_from="2026-04-22",
                publication_date_to="2026-04-22",
            )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].article_id, newer_article_id)
        self.assertEqual(cards[0].publication_date, "2026-04-22")

    def test_article_cards_are_sorted_by_publication_date_desc(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_article_card_views)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            older_document_key = self._insert_document(
                database_path,
                original_filename="ft-2026-04-21.pdf",
                source_name="Financial Times",
                document_key="message-1:attachment-1:hash-1",
            )
            newer_document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-22.pdf",
                source_name="Wall Street Journal",
                document_key="message-2:attachment-1:hash-2",
            )

            older_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=older_document_key,
                publication_date="2026-04-21",
                title="Older article",
                body_suffix="Older article body.",
                translated_title_zh="较早文章",
                summary_zh="较早文章摘要。",
                translated_body_zh="较早文章正文。",
                tags=["Markets", "Europe", "Trade"],
            )
            newer_article_id = self._insert_succeeded_article_with_enrichment(
                database_url=database_url,
                document_key=newer_document_key,
                publication_date="2026-04-22",
                title="Newer article",
                body_suffix="Newer article body.",
                translated_title_zh="较新文章",
                summary_zh="较新文章摘要。",
                translated_body_zh="较新文章正文。",
                tags=["Policy", "Hardware", "Trade"],
            )

            cards = list_article_card_views(database_url=database_url)

        self.assertEqual([card.article_id for card in cards], [newer_article_id, older_article_id])

    def _seed_article_with_enrichment(
        self,
        *,
        database_url: str,
        title_en: str,
        content_type: str,
        run_status: str,
        classification_reason: str = "auto.",
        tags: list[str] | None = None,
        document_key: str | None = None,
    ) -> "StoredFinalArticle":
        if document_key is None:
            document_key = f"message-{uuid.uuid4()}:attachment-1:hash-1"
            self._insert_document(
                pathlib.Path(database_url.replace("sqlite:///", "")),
                original_filename="seeded-doc.pdf",
                source_name="Seeded Source",
                document_key=document_key,
            )
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date="2026-04-20",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=self._build_parse_result(title=title_en, body_suffix="body."),
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

        enrichment = create_article_enrichment_run(
            database_url=database_url,
            article_id=article.article_id,
            parse_run_id=parse_run.parse_run_id,
            provider_name="gemini",
            model_name="gemini-2.5-flash",
            prompt_version="article-enrichment-v3",
            input_hash=f"hash-{article.article_id}",
        )
        if content_type == "advertisement":
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment.enrichment_run_id,
                translated_title_zh=None,
                summary_zh=None,
                translated_body_zh=None,
                translation_status="skipped",
                summary_status="skipped",
                tagging_status="skipped",
                tags=[],
                content_type=content_type,
                classification_reason=classification_reason,
            )
        else:
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment.enrichment_run_id,
                translated_title_zh="标题",
                summary_zh="摘要。",
                translated_body_zh="正文。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=tags or ["标签一", "标签二", "标签三"],
                content_type=content_type,
                classification_reason=classification_reason,
            )
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment.enrichment_run_id,
            status=run_status,
        )
        return article

    def test_list_article_card_views_excludes_skipped_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            article_visible = self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Visible Article",
                content_type="article",
                run_status="succeeded",
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            cards = list_article_card_views(database_url=database_url)

        titles = [card.title_en for card in cards]
        self.assertIn("Visible Article", titles)
        self.assertNotIn("Hidden Advertisement", titles)
        self.assertEqual(cards[0].article_id, article_visible.article_id)

    def test_get_overview_pending_count_excludes_skipped_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            overview = get_overview_view(database_url=database_url)

        self.assertEqual(overview.pending_article_count, 0)

    def test_get_overview_article_count_excludes_skipped_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Visible Article",
                content_type="article",
                run_status="succeeded",
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Hidden Advertisement",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            overview = get_overview_view(database_url=database_url)

        self.assertEqual(overview.article_count, 1)

    def test_get_filter_options_excludes_advertisement_only_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Normal",
                content_type="article",
                run_status="succeeded",
                tags=["T1", "T2", "T3"],
            )
            self._seed_article_with_enrichment(
                database_url=database_url,
                title_en="Ad",
                content_type="advertisement",
                run_status="skipped_advertisement",
            )

            filters = get_filter_options_view(database_url=database_url)

        self.assertIn("T1", filters.tags)

    def test_get_document_processing_detail_visible_articles_excludes_advertisements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            shared_document_key = "message-shared:attachment-1:hash-1"
            self._insert_document(
                pathlib.Path(str(database_path)),
                original_filename="shared-doc.pdf",
                source_name="Shared Source",
                document_key=shared_document_key,
            )

            # Create a single parse run with two articles so both appear in
            # list_latest_document_articles.
            parse_run = create_parse_run(
                database_url=database_url,
                document_key=shared_document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
            )
            two_article_parse_result = ParseResult(
                fragments=[
                    ArticleFragment(
                        title="Normal Article",
                        body_text="Normal body text.",
                        source_order=1,
                        continued_to_page="",
                        continued_from_page="",
                    ),
                    ArticleFragment(
                        title="Hidden Ad",
                        body_text="Ad body text.",
                        source_order=2,
                        continued_to_page="",
                        continued_from_page="",
                    ),
                ],
                match_decisions=[],
                articles=[
                    ParsedArticle(
                        article_order=1,
                        primary_source_order=1,
                        source_fragment_count=1,
                        title="Normal Article",
                        body_text="Normal body text.",
                        source_fragments=[
                            ArticleSource(source_order=1, fragment_role="front", sequence_index=1),
                        ],
                    ),
                    ParsedArticle(
                        article_order=2,
                        primary_source_order=2,
                        source_fragment_count=1,
                        title="Hidden Ad",
                        body_text="Ad body text.",
                        source_fragments=[
                            ArticleSource(source_order=2, fragment_role="front", sequence_index=1),
                        ],
                    ),
                ],
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                parse_result=two_article_parse_result,
                document_key=shared_document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
                status="succeeded",
            )
            articles = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )
            # articles are ordered by article_order; find each by title
            normal_article = next(a for a in articles if a.title_en == "Normal Article")
            ad_article = next(a for a in articles if a.title_en == "Hidden Ad")

            # Enrich normal article as a real article
            enrichment_normal = create_article_enrichment_run(
                database_url=database_url,
                article_id=normal_article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
                input_hash=f"hash-{normal_article.article_id}",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_normal.enrichment_run_id,
                translated_title_zh="正常文章",
                summary_zh="摘要。",
                translated_body_zh="正文。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=["标签一", "标签二", "标签三"],
                content_type="article",
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_normal.enrichment_run_id,
                status="succeeded",
            )

            # Enrich ad article as advertisement
            enrichment_ad = create_article_enrichment_run(
                database_url=database_url,
                article_id=ad_article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="article-enrichment-v3",
                input_hash=f"hash-{ad_article.article_id}",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=enrichment_ad.enrichment_run_id,
                translated_title_zh=None,
                summary_zh=None,
                translated_body_zh=None,
                translation_status="skipped",
                summary_status="skipped",
                tagging_status="skipped",
                tags=[],
                content_type="advertisement",
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=enrichment_ad.enrichment_run_id,
                status="skipped_advertisement",
            )

            create_document_processing_run(
                database_url=database_url,
                document_key=shared_document_key,
            )

            view = get_document_processing_detail_view(
                database_url=database_url,
                document_key=shared_document_key,
            )

        titles = [article.title_en for article in view.visible_articles]
        self.assertIn("Normal Article", titles)
        self.assertNotIn("Hidden Ad", titles)
        self.assertEqual(view.visible_article_count, 1)

    def _insert_document(
        self,
        database_path: pathlib.Path,
        *,
        original_filename: str,
        source_name: str,
        document_key: str = "message-1:attachment-1:hash-1",
    ) -> str:
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
                    source_name,
                    "message-1",
                    "attachment-1",
                    "news@example.com",
                    original_filename,
                    "hash-1",
                    "/tmp/ft-2026-04-22.pdf",
                    "imported",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key

    def _insert_import_run(self, database_path: pathlib.Path, *, created_document_count: int) -> str:
        run_id = "import-run-1"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO import_runs (
                    run_id,
                    source_name,
                    status,
                    query,
                    allowed_senders_json,
                    max_results,
                    created_document_count,
                    finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    run_id,
                    "gmail",
                    "succeeded",
                    "newer_than:7d",
                    "[]",
                    25,
                    created_document_count,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return run_id

    def _insert_document_processing_run(
        self,
        database_path: pathlib.Path,
        *,
        document_key: str,
        status: str,
        current_step: str,
        last_failure_step: str | None = None,
        last_error_message: str | None = None,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO document_processing_runs (
                    processing_run_id,
                    document_key,
                    status,
                    current_step,
                    last_failure_step,
                    last_error_message
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"processing-{document_key}",
                    document_key,
                    status,
                    current_step,
                    last_failure_step,
                    last_error_message,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _insert_article_processing_run(
        self,
        *,
        database_path: pathlib.Path,
        article_key: str,
        article_id: str,
        status: str,
        current_step: str,
        last_error_message: str | None = None,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                INSERT INTO article_processing_runs (
                    article_processing_run_id,
                    article_key,
                    article_id,
                    status,
                    current_step,
                    last_error_message
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"article-processing-{article_key}",
                    article_key,
                    article_id,
                    status,
                    current_step,
                    last_error_message,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _get_article_key(
        self,
        *,
        database_path: pathlib.Path,
        article_id: str,
    ) -> str:
        connection = sqlite3.connect(database_path)
        try:
            row = connection.execute(
                """
                SELECT article_key
                FROM final_articles
                WHERE article_id = ?
                """,
                (article_id,),
            ).fetchone()
        finally:
            connection.close()
        return row[0]

    def _build_parse_result(self, *, title: str, body_suffix: str) -> ParseResult:
        return ParseResult(
            fragments=[
                ArticleFragment(
                    title=title,
                    body_text="The policy outlook shifted rapidly.\nPlease turn to page A7",
                    source_order=1,
                    continued_to_page="A7",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Chipmakers prepare",
                    body_text=(
                        "Continued from PageOne after new proposals were circulated.\n"
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
                        "The policy outlook shifted rapidly.\n"
                        f"{body_suffix}"
                    ),
                    source_fragments=[
                        ArticleSource(source_order=1, fragment_role="front", sequence_index=1),
                        ArticleSource(source_order=2, fragment_role="back", sequence_index=2),
                    ],
                )
            ],
        )

    def _insert_succeeded_article_with_enrichment(
        self,
        *,
        database_url: str,
        document_key: str,
        publication_date: str,
        title: str,
        body_suffix: str,
        translated_title_zh: str | None,
        summary_zh: str | None,
        translated_body_zh: str | None,
        tags: list[str],
        enrichment_status: str = "succeeded",
    ) -> str:
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date=publication_date,
            continuation_matcher_name="gemini",
            continuation_matcher_version="2.5-flash",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=self._build_parse_result(
                title=title,
                body_suffix=body_suffix,
            ),
            document_key=document_key,
            publication_date=publication_date,
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
        enrichment_run = create_article_enrichment_run(
            database_url=database_url,
            article_id=article.article_id,
            parse_run_id=parse_run.parse_run_id,
            provider_name="gemini",
            model_name="gemini-2.5-flash",
            prompt_version="article-enrichment-v2",
            input_hash=f"hash-{article.article_id}",
        )
        record_article_enrichment_outputs(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            translated_title_zh=translated_title_zh,
            summary_zh=summary_zh,
            translated_body_zh=translated_body_zh,
            translation_status="partial" if enrichment_status == "partial" else "succeeded",
            summary_status="partial" if enrichment_status == "partial" else "succeeded",
            tagging_status="partial" if enrichment_status == "partial" else "succeeded",
            tags=tags,
        )
        finalize_article_enrichment_run(
            database_url=database_url,
            enrichment_run_id=enrichment_run.enrichment_run_id,
            status=enrichment_status,
        )
        return article.article_id

    def _insert_succeeded_article_without_enrichment(
        self,
        *,
        database_url: str,
        document_key: str,
        publication_date: str,
        title: str,
        body_suffix: str,
    ) -> str:
        parse_run = create_parse_run(
            database_url=database_url,
            document_key=document_key,
            parser_name="mineru",
            parser_version="vlm",
            publication_date=publication_date,
            continuation_matcher_name="gemini",
            continuation_matcher_version="2.5-flash",
        )
        record_parse_run_result(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            parse_result=self._build_parse_result(
                title=title,
                body_suffix=body_suffix,
            ),
            document_key=document_key,
            publication_date=publication_date,
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )
        return list_parse_run_final_articles(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
        )[0].article_id


if __name__ == "__main__":
    unittest.main()
