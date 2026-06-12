import pathlib
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from newspaper_translator.database import run_pending_migrations
except ImportError:
    run_pending_migrations = None

try:
    from newspaper_translator.article_store import (
        create_parse_run,
        finalize_parse_run,
        get_latest_article_enrichment,
        list_latest_document_articles,
        record_parse_run_result,
    )
    from newspaper_translator.gemini import ArticleSummaryTagResult, ArticleTranslationResult
    from newspaper_translator.mineru import MineruParsedDocument, MineruParsedPage
    from newspaper_translator.pdf import (
        ArticleFragment,
        ArticleSource,
        ParseMatchDecision,
        ParseResult,
        ParsedArticle,
    )
except ImportError:
    create_parse_run = None
    finalize_parse_run = None
    get_latest_article_enrichment = None
    list_latest_document_articles = None
    record_parse_run_result = None
    ArticleSummaryTagResult = None
    ArticleTranslationResult = None
    MineruParsedDocument = None
    MineruParsedPage = None
    ArticleFragment = None
    ArticleSource = None
    ParseMatchDecision = None
    ParseResult = None
    ParsedArticle = None

try:
    import newspaper_translator.document_processing as document_processing_module
    from newspaper_translator.document_processing import (
        claim_article_processing_run,
        claim_document_processing_run,
        create_article_processing_run,
        create_document_processing_run,
        create_scheduler_run,
        DrainResult,
        enqueue_document_article_processing_runs,
        enrich_document_articles,
        fail_article_processing_run,
        fail_document_processing_run,
        get_article_processing_run,
        get_document_processing_run,
        get_latest_scheduler_run,
        finalize_scheduler_run,
        get_scheduler_run,
        list_eligible_article_processing_runs,
        list_eligible_document_processing_runs,
        list_document_processing_runs,
        get_document_processing_max_failure_count,
        process_article_processing_run,
        process_document,
        ProcessingTickResult,
        recover_stale_article_runs,
        recover_stale_document_runs,
        request_manual_article_retry,
        run_processing_tick,
        run_article_processing_drain,
        run_document_processing_drain,
        run_scheduler_tick,
        succeed_article_processing_run,
        succeed_document_processing_run,
        request_manual_document_retry,
    )
except ImportError:
    document_processing_module = None
    claim_article_processing_run = None
    claim_document_processing_run = None
    create_article_processing_run = None
    create_document_processing_run = None
    create_scheduler_run = None
    DrainResult = None
    enqueue_document_article_processing_runs = None
    enrich_document_articles = None
    fail_article_processing_run = None
    fail_document_processing_run = None
    finalize_scheduler_run = None
    get_article_processing_run = None
    get_document_processing_run = None
    get_latest_scheduler_run = None
    get_scheduler_run = None
    list_eligible_article_processing_runs = None
    list_eligible_document_processing_runs = None
    list_document_processing_runs = None
    get_document_processing_max_failure_count = None
    process_article_processing_run = None
    process_document = None
    ProcessingTickResult = None
    recover_stale_article_runs = None
    recover_stale_document_runs = None
    request_manual_article_retry = None
    run_processing_tick = None
    run_article_processing_drain = None
    run_document_processing_drain = None
    run_scheduler_tick = None
    succeed_article_processing_run = None
    succeed_document_processing_run = None
    request_manual_document_retry = None


class DocumentProcessingTestMixin:
    """Shared helper methods for document processing tests.

    Not a TestCase — mix in alongside unittest.TestCase.
    """

    def _insert_document(
        self,
        database_path: pathlib.Path,
        document_key: str,
        *,
        raw_path: str = "/tmp/wsj-2026-04-20.pdf",
        original_filename: str = "wsj-2026-04-20.pdf",
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
                    "gmail",
                    document_key.split(":")[0],
                    "attachment-1",
                    "news@example.com",
                    original_filename,
                    document_key.split(":")[-1],
                    raw_path,
                    "imported",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return document_key

    def _persist_parsed_document_articles(
        self,
        *,
        database_url: str,
        document_key: str,
        article_count: int = 1,
    ) -> None:
        if article_count == 1:
            parse_result = self._build_parse_result()
        elif article_count == 2:
            parse_result = self._build_multi_article_parse_result()
        else:
            parse_result = self._build_n_article_parse_result(article_count)
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
            parse_result=parse_result,
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )

    def _persist_multi_article_document_articles(
        self,
        *,
        database_url: str,
        document_key: str,
    ) -> None:
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
            parse_result=self._build_multi_article_parse_result(),
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )

    def _persist_custom_parse_result(
        self,
        *,
        database_url: str,
        document_key: str,
        parse_result,
    ) -> None:
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
            parse_result=parse_result,
            document_key=document_key,
            publication_date="2026-04-20",
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="succeeded",
        )

    def _set_document_processing_status(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        status: str,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                UPDATE document_processing_runs
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE document_key = ?
                """,
                (status, document_key),
            )
            connection.commit()
        finally:
            connection.close()

    def _set_document_processing_attempt_age_seconds(
        self,
        *,
        database_path: pathlib.Path,
        document_key: str,
        age_seconds: int,
        automatic_failure_count: int | None = None,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            if automatic_failure_count is None:
                connection.execute(
                    """
                    UPDATE document_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE document_key = ?
                    """,
                    (age_seconds, document_key),
                )
            else:
                connection.execute(
                    """
                    UPDATE document_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        automatic_failure_count = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE document_key = ?
                    """,
                    (age_seconds, automatic_failure_count, document_key),
                )
            connection.commit()
        finally:
            connection.close()

    def _set_article_processing_attempt_age_seconds(
        self,
        *,
        database_path: pathlib.Path,
        article_key: str,
        age_seconds: int,
        automatic_failure_count: int | None = None,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            if automatic_failure_count is None:
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (age_seconds, article_key),
                )
            else:
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        last_attempt_started_at = datetime(CURRENT_TIMESTAMP, '-' || ? || ' seconds'),
                        lock_expires_at = datetime(CURRENT_TIMESTAMP, '-1 seconds'),
                        automatic_failure_count = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (age_seconds, automatic_failure_count, article_key),
                )
            connection.commit()
        finally:
            connection.close()

    def _set_scheduler_run_started_at(
        self,
        *,
        database_path: pathlib.Path,
        scheduler_run_id: str,
        started_at: str,
    ) -> None:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                UPDATE scheduler_runs
                SET started_at = ?
                WHERE scheduler_run_id = ?
                """,
                (started_at, scheduler_run_id),
            )
            connection.commit()
        finally:
            connection.close()

    def _build_n_article_parse_result(self, n: int):
        from newspaper_translator.pdf import ArticleFragment, ArticleSource, ParseMatchDecision, ParsedArticle, ParseResult
        fragments = [
            ArticleFragment(
                title=f"Article {i} title",
                body_text=f"Article {i} body.",
                source_order=i,
                continued_to_page="",
                continued_from_page="",
            )
            for i in range(1, n + 1)
        ]
        articles = [
            ParsedArticle(
                article_order=i,
                primary_source_order=i,
                source_fragment_count=1,
                title=f"Article {i} title",
                body_text=f"Article {i} body.",
                source_fragments=[
                    ArticleSource(
                        source_order=i,
                        fragment_role="single",
                        sequence_index=1,
                    )
                ],
            )
            for i in range(1, n + 1)
        ]
        return ParseResult(fragments=fragments, match_decisions=[], articles=articles)

    def _build_parse_result(self):
        return ParseResult(
            fragments=[
                ArticleFragment(
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="U.S. oil futures were trading near $90 a barrel Sunday.",
                    source_order=1,
                    continued_to_page="",
                    continued_from_page="",
                )
            ],
            match_decisions=[
                ParseMatchDecision(
                    front_source_order=None,
                    back_source_order=None,
                    decision_status="skipped",
                    decision_reason="single fragment article",
                    matcher_raw_response="[]",
                )
            ],
            articles=[
                ParsedArticle(
                    article_order=1,
                    primary_source_order=1,
                    source_fragment_count=1,
                    title="Big Oil Explores Farther Afield To Dodge Middle East Turmoil",
                    body_text="The oil companies want to maximize their production.",
                    source_fragments=[
                        ArticleSource(
                            source_order=1,
                            fragment_role="single",
                            sequence_index=1,
                        )
                    ],
                )
            ],
        )

    def _build_multi_article_parse_result(
        self,
        *,
        first_body_text: str = "First article body.",
        second_body_text: str = "Second article body.",
    ):
        return ParseResult(
            fragments=[
                ArticleFragment(
                    title="First article title",
                    body_text=first_body_text,
                    source_order=1,
                    continued_to_page="",
                    continued_from_page="",
                ),
                ArticleFragment(
                    title="Second article title",
                    body_text=second_body_text,
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
                    title="First article title",
                    body_text=first_body_text,
                    source_fragments=[
                        ArticleSource(
                            source_order=1,
                            fragment_role="single",
                            sequence_index=1,
                        )
                    ],
                ),
                ParsedArticle(
                    article_order=2,
                    primary_source_order=2,
                    source_fragment_count=1,
                    title="Second article title",
                    body_text=second_body_text,
                    source_fragments=[
                        ArticleSource(
                            source_order=2,
                            fragment_role="single",
                            sequence_index=1,
                        )
                    ],
                ),
            ],
        )


class _FakeTranslator:
    def __call__(self, article):
        return ArticleTranslationResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translated_title_zh="大型石油公司远赴他处避开中东动荡",
            translated_body_zh="多家能源企业正加速在非洲和南美寻找新机会。",
        )


class _SelectiveFailingTranslator:
    def __init__(self, *, failing_titles: set[str]) -> None:
        self._failing_titles = failing_titles

    def __call__(self, article):
        if article.title_en in self._failing_titles:
            raise RuntimeError("translation timeout")
        return ArticleTranslationResult(
            content_type="article",
            classification_reason="Regular newspaper article.",
            translated_title_zh=f"{article.title_en} 中文",
            translated_body_zh=f"{article.body_text_en} 中文",
        )


class _FakeSummarizerTagger:
    def __call__(self, *, article, translated_title_zh: str, translated_body_zh: str):
        return ArticleSummaryTagResult(
            summary_zh="油企为避开中东风险，正把勘探重点转向非洲和南美。",
            tags=["能源", "石油", "中东局势"],
        )


class _FailingSummarizerTagger:
    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, *, article, translated_title_zh: str, translated_body_zh: str):
        raise RuntimeError(self._message)


class _FakeMineruClient:
    def __init__(self, *, parsed_document) -> None:
        self._parsed_document = parsed_document

    def parse_pdf_by_pages(self, *, pdf_path: pathlib.Path, output_root: pathlib.Path, document_key=None, page_state_store=None):
        return self._parsed_document
