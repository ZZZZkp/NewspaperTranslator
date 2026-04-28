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
    from newspaper_translator.article_store import (
        create_article_enrichment_run,
        create_parse_run,
        finalize_article_enrichment_run,
        finalize_parse_run,
        get_latest_article_enrichment,
        list_latest_document_articles,
        list_parse_run_continuation_matches,
        list_parse_run_final_articles,
        list_parse_run_fragments,
        list_parse_runs,
        record_article_enrichment_outputs,
        record_parse_run_result,
        update_parse_run_source_artifacts,
    )
    from newspaper_translator.database import run_pending_migrations
    from newspaper_translator.pdf import (
        ArticleFragment,
        ArticleSource,
        ParseMatchDecision,
        ParseResult,
        ParsedArticle,
    )
except ImportError:
    create_article_enrichment_run = None
    create_parse_run = None
    finalize_article_enrichment_run = None
    finalize_parse_run = None
    get_latest_article_enrichment = None
    list_latest_document_articles = None
    list_parse_run_continuation_matches = None
    list_parse_run_final_articles = None
    list_parse_run_fragments = None
    list_parse_runs = None
    record_article_enrichment_outputs = None
    record_parse_run_result = None
    run_pending_migrations = None
    update_parse_run_source_artifacts = None
    ArticleFragment = None
    ArticleSource = None
    ParseMatchDecision = None
    ParseResult = None
    ParsedArticle = None


class ArticleStoreTests(unittest.TestCase):
    def test_persists_parse_run_history_and_latest_visible_articles(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_parse_run)
        self.assertIsNotNone(record_parse_run_result)
        self.assertIsNotNone(list_latest_document_articles)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)
            document_key = self._insert_document(
                database_path,
                original_filename="wsj-2026-04-20.pdf",
            )

            first_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            update_parse_run_source_artifacts(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
                mineru_batch_id="batch-1",
                mineru_file_id="file-1",
                markdown_path="/tmp/wsj-2026-04-20/full.md",
            )
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
                parse_result=self._build_parse_result(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_suffix="The oil companies want to maximize their production.",
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
                status="succeeded",
            )

            second_run = create_parse_run(
                database_url=database_url,
                document_key=document_key,
                parser_name="mineru",
                parser_version="vlm",
                publication_date="2026-04-20",
                continuation_matcher_name="gemini",
                continuation_matcher_version="2.5-flash",
            )
            finalize_parse_run(
                database_url=database_url,
                parse_run_id=second_run.parse_run_id,
                status="failed",
                error_message="publication date missing from markdown fallback",
            )

            parse_runs = list_parse_runs(database_url=database_url, document_key=document_key)
            fragments = list_parse_run_fragments(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
            )
            matches = list_parse_run_continuation_matches(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
            )
            final_articles = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
            )
            latest_articles = list_latest_document_articles(
                database_url=database_url,
                document_key=document_key,
            )

        self.assertEqual([run.status for run in parse_runs], ["failed", "succeeded"])
        self.assertEqual(len(fragments), 2)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].decision_status, "accepted")
        self.assertEqual(len(final_articles), 1)
        self.assertEqual(final_articles[0].source_fragment_count, 2)
        self.assertEqual(len(latest_articles), 1)
        self.assertEqual(latest_articles[0].parse_run_id, first_run.parse_run_id)
        self.assertIn("The oil companies want to maximize their production.", latest_articles[0].body_text_en)

    def test_persists_enrichment_history_and_keeps_latest_usable_result(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_enrichment_run)
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

            usable_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="v1",
                input_hash="hash-1",
            )
            record_article_enrichment_outputs(
                database_url=database_url,
                enrichment_run_id=usable_run.enrichment_run_id,
                translated_title_zh="大石油公司向更远地区寻找新油源",
                summary_zh="油企正在加速寻找新的油气勘探区。",
                translated_body_zh="在中东局势动荡之际，多家油企正在扩大勘探范围。",
                translation_status="succeeded",
                summary_status="succeeded",
                tagging_status="succeeded",
                tags=["能源", "石油", "中东局势"],
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=usable_run.enrichment_run_id,
                status="succeeded",
            )

            failed_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="v2",
                input_hash="hash-1",
            )
            finalize_article_enrichment_run(
                database_url=database_url,
                enrichment_run_id=failed_run.enrichment_run_id,
                status="failed",
                error_message="translation timeout",
            )

            latest_enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )

        self.assertEqual(latest_enrichment.enrichment_run_id, usable_run.enrichment_run_id)
        self.assertEqual(latest_enrichment.status, "succeeded")
        self.assertEqual(latest_enrichment.translated_title_zh, "大石油公司向更远地区寻找新油源")
        self.assertEqual(latest_enrichment.tags, ["能源", "石油", "中东局势"])

    def test_rejects_successful_tagging_outside_allowed_range(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_article_enrichment_run)
        self.assertIsNotNone(record_article_enrichment_outputs)

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
            enrichment_run = create_article_enrichment_run(
                database_url=database_url,
                article_id=article.article_id,
                parse_run_id=parse_run.parse_run_id,
                provider_name="gemini",
                model_name="gemini-2.5-flash",
                prompt_version="v1",
                input_hash="hash-1",
            )

            with self.assertRaisesRegex(ValueError, "3 to 8 tags"):
                record_article_enrichment_outputs(
                    database_url=database_url,
                    enrichment_run_id=enrichment_run.enrichment_run_id,
                    translated_title_zh="大石油公司向更远地区寻找新油源",
                    summary_zh="油企正在加速寻找新的油气勘探区。",
                    translated_body_zh="在中东局势动荡之际，多家油企正在扩大勘探范围。",
                    translation_status="succeeded",
                    summary_status="succeeded",
                    tagging_status="succeeded",
                    tags=["能源", "石油"],
                )

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


if __name__ == "__main__":
    unittest.main()
