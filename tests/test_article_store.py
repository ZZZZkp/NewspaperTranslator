import pathlib
import sqlite3
from types import SimpleNamespace
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
        get_final_article,
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
    get_final_article = None
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
    def test_loads_fragment_page_numbers_and_article_source_page_numbers(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(list_parse_run_fragments)
        self.assertIsNotNone(list_parse_run_final_articles)

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = pathlib.Path(temp_dir) / "app.db"
            database_url = f"sqlite:///{database_path}"
            run_pending_migrations(database_url)

            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """
                    INSERT INTO parse_runs (
                        parse_run_id,
                        document_key,
                        status,
                        parser_name,
                        parser_version,
                        publication_date
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "parse-run-1",
                        "document-1",
                        "succeeded",
                        "mineru",
                        "vlm",
                        "2026-04-20",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO article_fragments (
                        fragment_id,
                        parse_run_id,
                        source_order,
                        page_number,
                        title,
                        body_text,
                        continued_to_page,
                        continued_from_page,
                        is_continuation_candidate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "fragment-1",
                        "parse-run-1",
                        1,
                        1,
                        "Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                        "Front fragment body",
                        "A7",
                        "",
                        1,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO article_fragments (
                        fragment_id,
                        parse_run_id,
                        source_order,
                        page_number,
                        title,
                        body_text,
                        continued_to_page,
                        continued_from_page,
                        is_continuation_candidate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "fragment-2",
                        "parse-run-1",
                        2,
                        7,
                        "Big Oil Explores Farther Out",
                        "Back fragment body",
                        "",
                        "PageOne",
                        1,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO final_articles (
                        article_id,
                        parse_run_id,
                        document_key,
                        publication_date,
                        article_order,
                        primary_source_order,
                        source_fragment_count,
                        title_en,
                        body_text_en
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "article-1",
                        "parse-run-1",
                        "document-1",
                        "2026-04-20",
                        1,
                        1,
                        2,
                        "Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                        "Merged article body",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO final_article_fragments (
                        article_id,
                        fragment_id,
                        fragment_role,
                        sequence_index
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("article-1", "fragment-1", "front", 1),
                )
                connection.execute(
                    """
                    INSERT INTO final_article_fragments (
                        article_id,
                        fragment_id,
                        fragment_role,
                        sequence_index
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("article-1", "fragment-2", "back", 2),
                )
                connection.commit()
            finally:
                connection.close()

            fragments = list_parse_run_fragments(
                database_url=database_url,
                parse_run_id="parse-run-1",
            )
            final_articles = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id="parse-run-1",
            )

        self.assertEqual(getattr(fragments[0], "page_number", None), 1)
        self.assertEqual(getattr(fragments[1], "page_number", None), 7)
        self.assertEqual(getattr(final_articles[0], "source_page_numbers", None), [1, 7])

    def test_record_parse_run_result_persists_fragment_page_numbers(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_parse_run)
        self.assertIsNotNone(record_parse_run_result)
        self.assertIsNotNone(list_parse_run_fragments)

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
                parse_result=ParseResult(
                    fragments=[
                        SimpleNamespace(
                            title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                            body_text="Front fragment body",
                            source_order=1,
                            page_number=1,
                            continued_to_page="A7",
                            continued_from_page="",
                        ),
                        SimpleNamespace(
                            title="Big Oil Explores Farther Out",
                            body_text="Back fragment body",
                            source_order=2,
                            page_number=7,
                            continued_to_page="",
                            continued_from_page="PageOne",
                        ),
                    ],
                    match_decisions=[],
                    articles=[
                        ParsedArticle(
                            article_order=1,
                            primary_source_order=1,
                            source_fragment_count=2,
                            title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                            body_text="Merged article body",
                            source_fragments=[
                                ArticleSource(source_order=1, fragment_role="front", sequence_index=1),
                                ArticleSource(source_order=2, fragment_role="back", sequence_index=2),
                            ],
                        )
                    ],
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )

            fragments = list_parse_run_fragments(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )

        self.assertEqual([fragment.page_number for fragment in fragments], [1, 7])

    def test_reuses_article_key_for_same_document_page_and_similar_title_across_parse_runs(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_parse_run)
        self.assertIsNotNone(record_parse_run_result)
        self.assertIsNotNone(list_parse_run_final_articles)

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
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
                parse_result=self._build_identity_parse_result(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="First version of the article body.",
                    source_pages=[1, 7],
                ),
                document_key=document_key,
                publication_date="2026-04-20",
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
            record_parse_run_result(
                database_url=database_url,
                parse_run_id=second_run.parse_run_id,
                parse_result=self._build_identity_parse_result(
                    title="Big Oil Explores Farther Afield to Dodge Middle East Turmoil ",
                    body_text="Second version of the article body with small cleanup.",
                    source_pages=[1, 7],
                ),
                document_key=document_key,
                publication_date="2026-04-20",
            )

            first_article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=first_run.parse_run_id,
            )[0]
            second_article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=second_run.parse_run_id,
            )[0]

        self.assertTrue(getattr(first_article, "article_key", ""))
        self.assertEqual(first_article.article_key, second_article.article_key)

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

    def test_loads_one_final_article_by_article_id_for_enrichment_input(self) -> None:
        self.assertIsNotNone(run_pending_migrations)
        self.assertIsNotNone(create_parse_run)
        self.assertIsNotNone(record_parse_run_result)
        self.assertIsNotNone(get_final_article)

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
            stored_article = list_parse_run_final_articles(
                database_url=database_url,
                parse_run_id=parse_run.parse_run_id,
            )[0]

            loaded_article = get_final_article(
                database_url=database_url,
                article_id=stored_article.article_id,
            )

        self.assertEqual(loaded_article.article_id, stored_article.article_id)
        self.assertEqual(loaded_article.parse_run_id, parse_run.parse_run_id)
        self.assertEqual(loaded_article.document_key, document_key)
        self.assertEqual(loaded_article.publication_date, "2026-04-20")
        self.assertEqual(
            loaded_article.title_en,
            "Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
        )
        self.assertIn(
            "The oil companies want to maximize their production.",
            loaded_article.body_text_en,
        )

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

    def _build_identity_parse_result(
        self,
        *,
        title: str,
        body_text: str,
        source_pages: list[int],
    ) -> ParseResult:
        fragments = [
            SimpleNamespace(
                title=title if index == 0 else f"{title} fragment {index + 1}",
                body_text=f"{body_text} fragment {index + 1}",
                source_order=index + 1,
                page_number=page_number,
                continued_to_page="A7" if index == 0 and len(source_pages) > 1 else "",
                continued_from_page="PageOne" if index > 0 else "",
            )
            for index, page_number in enumerate(source_pages)
        ]
        return ParseResult(
            fragments=fragments,
            match_decisions=[],
            articles=[
                ParsedArticle(
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=len(source_pages),
                    title=title,
                    body_text=body_text,
                    source_fragments=[
                        ArticleSource(
                            source_order=index + 1,
                            fragment_role="standalone" if len(source_pages) == 1 else ("front" if index == 0 else "back"),
                            sequence_index=index + 1,
                        )
                        for index, _page_number in enumerate(source_pages)
                    ],
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
