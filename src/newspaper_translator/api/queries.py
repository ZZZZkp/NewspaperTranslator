from dataclasses import dataclass
import sqlite3
from typing import Literal, overload

from newspaper_translator.article_content import extract_local_image_paths_and_clean_text
from newspaper_translator.article_store import (
    get_final_article,
    get_latest_article_enrichment,
    list_article_images,
    list_latest_document_articles,
)
from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.document_processing import (
    get_article_processing_run,
    get_document_processing_run,
)

_LATEST_USABLE_ENRICHMENT_SUBQUERY = """
SELECT r.article_id, r.status
FROM article_enrichment_runs r
WHERE r.status IN ('succeeded', 'partial', 'skipped_advertisement')
  AND r.finished_at = (
        SELECT MAX(r2.finished_at)
        FROM article_enrichment_runs r2
        WHERE r2.article_id = r.article_id
          AND r2.status IN ('succeeded', 'partial', 'skipped_advertisement')
  )
"""

_NOT_SKIPPED_ADVERTISEMENT_CLAUSE = """
NOT EXISTS (
    SELECT 1
    FROM ({latest}) latest
    WHERE latest.article_id = a.article_id
      AND latest.status = 'skipped_advertisement'
)
""".format(latest=_LATEST_USABLE_ENRICHMENT_SUBQUERY)


@dataclass(frozen=True)
class ArticleCardView:
    article_id: str
    document_key: str
    source_name: str
    publication_date: str
    page_label: str
    title_en: str
    title_zh: str | None
    summary_zh: str | None
    tags: list[str]
    hero_image_url: str | None
    reading_status: str
    quality_flags: list[str]
    processing_badges: list[str]


@dataclass(frozen=True)
class OverviewView:
    imported_document_count: int
    article_count: int
    pending_article_count: int
    processing_document_count: int
    pending_exception_count: int


@dataclass(frozen=True)
class ArticleDetailView:
    article_id: str
    document_key: str
    source_name: str
    publication_date: str
    page_label: str
    title_en: str
    title_zh: str | None
    summary_zh: str | None
    tags: list[str]
    body_text_en: str
    body_text_zh: str | None
    images: list[str]
    hero_image_url: str | None
    quality: dict[str, object]
    processing: dict[str, object]


@dataclass(frozen=True)
class FilterOptionsView:
    sources: list[str]
    tags: list[str]


@dataclass(frozen=True)
class PaginationView:
    page: int
    page_size: int
    total_count: int
    total_pages: int


@dataclass(frozen=True)
class ArticleProcessingFilterOptionsView:
    statuses: list[str]
    sources: list[str]
    steps: list[str]
    error_messages: list[str]


@dataclass(frozen=True)
class DocumentVisibleArticleView:
    article_id: str
    publication_date: str
    title_en: str
    title_zh: str | None
    summary_zh: str | None
    reading_status: str


@dataclass(frozen=True)
class DocumentProcessingDetailView:
    processing_run_id: str
    scheduler_run_id: str | None
    document_key: str
    source_name: str
    original_filename: str
    sender: str
    raw_path: str
    import_status: str
    status: str
    current_step: str
    automatic_failure_count: int
    last_failure_step: str | None
    last_error_message: str | None
    last_attempt_started_at: str | None
    last_attempt_finished_at: str | None
    locked_by: str | None
    lock_expires_at: str | None
    created_at: str
    updated_at: str
    latest_error_summary: str
    visible_article_count: int
    visible_articles: list[DocumentVisibleArticleView]


@dataclass(frozen=True)
class ArticleProcessingDetailView:
    article_processing_run_id: str
    article_key: str
    article_id: str
    document_key: str
    source_name: str
    original_filename: str
    publication_date: str
    title_en: str
    source_page_numbers: list[int]
    status: str
    current_step: str
    automatic_failure_count: int
    last_error_message: str | None
    last_success_input_hash: str | None
    last_attempt_started_at: str | None
    last_attempt_finished_at: str | None
    locked_by: str | None
    lock_expires_at: str | None
    created_at: str
    updated_at: str
    latest_error_summary: str
    content_type: str
    classification_reason: str
    latest_enrichment_status: str | None


@dataclass(frozen=True)
class ArticleProcessingCardView:
    article_processing_run_id: str
    article_key: str
    article_id: str
    document_key: str
    source_name: str
    original_filename: str
    publication_date: str
    title_en: str
    source_page_numbers: list[int]
    status: str
    current_step: str
    automatic_failure_count: int
    latest_error_summary: str


ArticleCardList = list[ArticleCardView]
ArticleCardPage = tuple[ArticleCardList, PaginationView]
ArticleProcessingCardList = list[ArticleProcessingCardView]
ArticleProcessingCardPage = tuple[ArticleProcessingCardList, PaginationView]


def _normalize_pagination(*, page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), max(page_size, 1)


def _build_pagination_view(*, page: int, page_size: int, total_count: int) -> PaginationView:
    total_pages = 0
    if total_count > 0:
        total_pages = (total_count + page_size - 1) // page_size
    return PaginationView(
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
    )


def _build_article_processing_where_clauses(
    *,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("r.status = ?")
        params.append(status)
    if source:
        clauses.append("d.source_name = ?")
        params.append(source)
    if publication_date_from:
        clauses.append("a.publication_date >= ?")
        params.append(publication_date_from)
    if publication_date_to:
        clauses.append("a.publication_date <= ?")
        params.append(publication_date_to)
    if step:
        clauses.append("r.current_step = ?")
        params.append(step)
    if error_message:
        clauses.append("r.last_error_message = ?")
        params.append(error_message)
    return clauses, params


def _build_article_card_filters(
    *,
    source: str | None = None,
    tag: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    reading_status: str | None = None,
    processing_status: str | None = None,
) -> tuple[str, list[object]]:
    query = (
        """
    FROM final_articles a
    JOIN documents d
        ON d.document_key = a.document_key
    JOIN parse_runs p
        ON p.parse_run_id = a.parse_run_id
    WHERE p.status = 'succeeded'
      AND p.parse_run_id = (
            SELECT p2.parse_run_id
            FROM parse_runs p2
            WHERE p2.document_key = a.document_key
              AND p2.status = 'succeeded'
            ORDER BY p2.finished_at DESC, p2.rowid DESC
            LIMIT 1
      )
      AND """
        + _NOT_SKIPPED_ADVERTISEMENT_CLAUSE
    )
    params: list[object] = []
    if source:
        query += " AND d.source_name = ?"
        params.append(source)
    if tag:
        query += """
         AND EXISTS (
                SELECT 1
                FROM article_tags t
                JOIN article_enrichment_runs r
                    ON r.enrichment_run_id = t.enrichment_run_id
                WHERE r.article_id = a.article_id
                  AND r.status IN ('partial', 'succeeded')
                  AND t.tag_text = ?
         )
        """
        params.append(tag)
    if publication_date_from:
        query += " AND a.publication_date >= ?"
        params.append(publication_date_from)
    if publication_date_to:
        query += " AND a.publication_date <= ?"
        params.append(publication_date_to)
    if reading_status == "ready":
        query += """
         AND EXISTS (
                SELECT 1
                FROM ({latest}) latest
                WHERE latest.article_id = a.article_id
         )
        """.format(latest=_LATEST_USABLE_ENRICHMENT_SUBQUERY)
    elif reading_status == "english_fallback":
        query += """
         AND NOT EXISTS (
                SELECT 1
                FROM ({latest}) latest
                WHERE latest.article_id = a.article_id
         )
        """.format(latest=_LATEST_USABLE_ENRICHMENT_SUBQUERY)
    if processing_status == "partial_enrichment":
        query += """
         AND EXISTS (
                SELECT 1
                FROM ({latest}) latest
                WHERE latest.article_id = a.article_id
                  AND latest.status = 'partial'
         )
        """.format(latest=_LATEST_USABLE_ENRICHMENT_SUBQUERY)
    return query, params


def get_overview_view(*, database_url: str) -> OverviewView:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        imported_document_count = connection.execute(
            """
            SELECT COALESCE(SUM(created_document_count), 0)
            FROM import_runs
            WHERE DATE(finished_at) = DATE('now')
            """
        ).fetchone()[0]
        article_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM final_articles a
            WHERE a.parse_run_id IN (
                SELECT p.parse_run_id
                FROM parse_runs p
                WHERE p.status = 'succeeded'
                  AND DATE(p.finished_at) = DATE('now')
            )
              AND """
            + _NOT_SKIPPED_ADVERTISEMENT_CLAUSE
        ).fetchone()[0]
        pending_article_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM final_articles a
            WHERE a.parse_run_id IN (
                SELECT p.parse_run_id
                FROM parse_runs p
                WHERE p.status = 'succeeded'
                  AND p.parse_run_id = (
                        SELECT p2.parse_run_id
                        FROM parse_runs p2
                        WHERE p2.document_key = a.document_key
                          AND p2.status = 'succeeded'
                        ORDER BY p2.finished_at DESC, p2.rowid DESC
                        LIMIT 1
                  )
            )
              AND NOT EXISTS (
                    SELECT 1
                    FROM article_enrichment_runs r
                    WHERE r.article_id = a.article_id
                      AND r.status = 'succeeded'
              )
              AND """
            + _NOT_SKIPPED_ADVERTISEMENT_CLAUSE
        ).fetchone()[0]
        processing_document_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM document_processing_runs
            WHERE status = 'running'
            """
        ).fetchone()[0]
        pending_exception_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM document_processing_runs
            WHERE status IN ('failed_retryable', 'failed_terminal', 'manual_retry_requested')
            """
        ).fetchone()[0]
    finally:
        connection.close()

    return OverviewView(
        imported_document_count=imported_document_count,
        article_count=article_count,
        pending_article_count=pending_article_count,
        processing_document_count=processing_document_count,
        pending_exception_count=pending_exception_count,
    )


def get_filter_options_view(*, database_url: str) -> FilterOptionsView:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        source_rows = connection.execute(
            """
            SELECT DISTINCT d.source_name
            FROM documents d
            JOIN parse_runs p
                ON p.document_key = d.document_key
            WHERE p.status = 'succeeded'
            ORDER BY d.source_name ASC
            """
        ).fetchall()
        tag_rows = connection.execute(
            """
            SELECT DISTINCT t.tag_text
            FROM article_tags t
            JOIN article_enrichment_runs r
                ON r.enrichment_run_id = t.enrichment_run_id
            JOIN final_articles a
                ON a.article_id = r.article_id
            WHERE r.status IN ('partial', 'succeeded')
              AND """
            + _NOT_SKIPPED_ADVERTISEMENT_CLAUSE
            + """
            ORDER BY t.tag_text ASC
            """
        ).fetchall()
    finally:
        connection.close()

    return FilterOptionsView(
        sources=[row[0] for row in source_rows],
        tags=[row[0] for row in tag_rows],
    )


def get_article_detail_view(*, database_url: str, article_id: str) -> ArticleDetailView:
    article = get_final_article(
        database_url=database_url,
        article_id=article_id,
    )
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        source_row = connection.execute(
            """
            SELECT source_name
            FROM documents
            WHERE document_key = ?
            """,
            (article.document_key,),
        ).fetchone()
        parse_row = connection.execute(
            """
            SELECT status
            FROM parse_runs
            WHERE parse_run_id = ?
            """,
            (article.parse_run_id,),
        ).fetchone()
        processing_row = connection.execute(
            """
            SELECT status
            FROM document_processing_runs
            WHERE document_key = ?
            """,
            (article.document_key,),
        ).fetchone()
    finally:
        connection.close()

    title_zh = None
    summary_zh = None
    body_text_zh = None
    tags: list[str] = []
    enrichment_status = "unavailable"
    try:
        enrichment = get_latest_article_enrichment(
            database_url=database_url,
            article_id=article.article_id,
        )
    except LookupError:
        enrichment = None
    if enrichment is not None:
        title_zh = enrichment.translated_title_zh
        summary_zh = enrichment.summary_zh
        body_text_zh = enrichment.translated_body_zh
        tags = enrichment.tags
        enrichment_status = enrichment.status
    if body_text_zh is not None:
        _, body_text_zh = extract_local_image_paths_and_clean_text(body_text_zh)

    images = [
        image.image_path
        for image in list_article_images(
            database_url=database_url,
            article_id=article.article_id,
        )
    ]

    return ArticleDetailView(
        article_id=article.article_id,
        document_key=article.document_key,
        source_name=source_row[0] if source_row else "",
        publication_date=article.publication_date,
        page_label="",
        title_en=article.title_en,
        title_zh=title_zh,
        summary_zh=summary_zh,
        tags=tags,
        body_text_en=article.body_text_en,
        body_text_zh=body_text_zh,
        images=images,
        hero_image_url=images[0] if images else None,
        quality={
            "confidence": "high",
            "flags": [],
        },
        processing={
            "document_status": processing_row[0] if processing_row else "unknown",
            "latest_parse_status": parse_row[0] if parse_row else "unknown",
            "latest_enrichment_status": enrichment_status,
        },
    )


def get_document_processing_detail_view(
    *,
    database_url: str,
    document_key: str,
) -> DocumentProcessingDetailView:
    run = get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        document_row = connection.execute(
            """
            SELECT source_name, original_filename, sender, raw_path, import_status
            FROM documents
            WHERE document_key = ?
            """,
            (document_key,),
        ).fetchone()
    finally:
        connection.close()

    if document_row is None:
        raise LookupError(f"Document not found: {document_key}")

    visible_articles: list[DocumentVisibleArticleView] = []
    for article in list_latest_document_articles(
        database_url=database_url,
        document_key=document_key,
    ):
        title_zh = None
        summary_zh = None
        reading_status = "english_fallback"
        try:
            enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=article.article_id,
            )
        except LookupError:
            enrichment = None

        if enrichment is not None and enrichment.status == "skipped_advertisement":
            continue

        if enrichment is not None:
            title_zh = enrichment.translated_title_zh
            summary_zh = enrichment.summary_zh
            reading_status = "ready"

        visible_articles.append(
            DocumentVisibleArticleView(
                article_id=article.article_id,
                publication_date=article.publication_date,
                title_en=article.title_en,
                title_zh=title_zh,
                summary_zh=summary_zh,
                reading_status=reading_status,
            )
        )

    latest_error_summary = "当前没有错误。"
    if run.last_error_message and run.last_failure_step:
        latest_error_summary = f"{run.last_failure_step}: {run.last_error_message}"
    elif run.last_error_message:
        latest_error_summary = run.last_error_message

    return DocumentProcessingDetailView(
        processing_run_id=run.processing_run_id,
        scheduler_run_id=run.scheduler_run_id,
        document_key=run.document_key,
        source_name=document_row[0],
        original_filename=document_row[1],
        sender=document_row[2],
        raw_path=document_row[3],
        import_status=document_row[4],
        status=run.status,
        current_step=run.current_step,
        automatic_failure_count=run.automatic_failure_count,
        last_failure_step=run.last_failure_step,
        last_error_message=run.last_error_message,
        last_attempt_started_at=run.last_attempt_started_at,
        last_attempt_finished_at=run.last_attempt_finished_at,
        locked_by=run.locked_by,
        lock_expires_at=run.lock_expires_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        latest_error_summary=latest_error_summary,
        visible_article_count=len(visible_articles),
        visible_articles=visible_articles,
    )


def get_article_processing_detail_view(
    *,
    database_url: str,
    article_key: str,
) -> ArticleProcessingDetailView:
    run = get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )
    article = get_final_article(
        database_url=database_url,
        article_id=run.article_id,
    )
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        document_row = connection.execute(
            """
            SELECT source_name, original_filename
            FROM documents
            WHERE document_key = ?
            """,
            (article.document_key,),
        ).fetchone()
    finally:
        connection.close()

    if document_row is None:
        raise LookupError(f"Document not found for article processing: {article.document_key}")

    latest_error_summary = "当前没有错误。"
    if run.last_error_message:
        latest_error_summary = f"{run.current_step}: {run.last_error_message}"

    content_type = "article"
    classification_reason = ""
    latest_enrichment_status: str | None = None
    try:
        latest_enrichment = get_latest_article_enrichment(
            database_url=database_url,
            article_id=article.article_id,
        )
    except LookupError:
        latest_enrichment = None
    if latest_enrichment is not None:
        content_type = latest_enrichment.content_type
        classification_reason = latest_enrichment.classification_reason
        latest_enrichment_status = latest_enrichment.status

    return ArticleProcessingDetailView(
        article_processing_run_id=run.article_processing_run_id,
        article_key=run.article_key,
        article_id=run.article_id,
        document_key=article.document_key,
        source_name=document_row[0],
        original_filename=document_row[1],
        publication_date=article.publication_date,
        title_en=article.title_en,
        source_page_numbers=article.source_page_numbers,
        status=run.status,
        current_step=run.current_step,
        automatic_failure_count=run.automatic_failure_count,
        last_error_message=run.last_error_message,
        last_success_input_hash=run.last_success_input_hash,
        last_attempt_started_at=run.last_attempt_started_at,
        last_attempt_finished_at=run.last_attempt_finished_at,
        locked_by=run.locked_by,
        lock_expires_at=run.lock_expires_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        latest_error_summary=latest_error_summary,
        content_type=content_type,
        classification_reason=classification_reason,
        latest_enrichment_status=latest_enrichment_status,
    )


@overload
def list_article_processing_card_views(
    *,
    database_url: str,
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
    include_pagination: Literal[False] = False,
) -> ArticleProcessingCardList: ...


@overload
def list_article_processing_card_views(
    *,
    database_url: str,
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
    include_pagination: Literal[True],
) -> ArticleProcessingCardPage: ...


def list_article_processing_card_views(
    *,
    database_url: str,
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
    include_pagination: bool = False,
) -> ArticleProcessingCardList | ArticleProcessingCardPage:
    """List article-processing runs.

    Default mode preserves the legacy query-layer contract and returns only the
    list of rows so existing callers can remain unchanged.

    Set ``include_pagination=True`` to receive ``(items, pagination)``.
    Pagination normalizes non-positive ``page`` and ``page_size`` to ``1``.
    When ``limit`` is provided it overrides ``page_size`` for backward
    compatibility with pre-pagination callers. Empty result sets report
    ``total_pages == 0``.
    """
    if limit is not None:
        page_size = limit
    page, page_size = _normalize_pagination(page=page, page_size=page_size)
    offset = (page - 1) * page_size
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        base_query = """
        FROM article_processing_runs r
        JOIN final_articles a
            ON a.article_id = r.article_id
        JOIN documents d
            ON d.document_key = a.document_key
        """
        clauses, params = _build_article_processing_where_clauses(
            status=status,
            source=source,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
            step=step,
            error_message=error_message,
        )
        if clauses:
            base_query += " WHERE " + " AND ".join(clauses)
        total_count = connection.execute(
            "SELECT COUNT(*) " + base_query,
            tuple(params),
        ).fetchone()[0]
        query = """
        SELECT
            r.article_processing_run_id,
            r.article_key,
            r.article_id,
            a.document_key,
            d.source_name,
            d.original_filename,
            a.publication_date,
            a.title_en,
            r.status,
            r.current_step,
            r.automatic_failure_count,
            r.last_error_message
        """ + base_query
        query += " ORDER BY r.updated_at DESC, r.created_at DESC, r.rowid DESC LIMIT ? OFFSET ?"
        rows = connection.execute(query, tuple([*params, page_size, offset])).fetchall()
    finally:
        connection.close()

    cards: list[ArticleProcessingCardView] = []
    for row in rows:
        article = get_final_article(
            database_url=database_url,
            article_id=row[2],
        )
        latest_error_summary = "当前没有错误。"
        if row[11]:
            latest_error_summary = f"{row[9]}: {row[11]}"
        cards.append(
            ArticleProcessingCardView(
                article_processing_run_id=row[0],
                article_key=row[1],
                article_id=row[2],
                document_key=row[3],
                source_name=row[4],
                original_filename=row[5],
                publication_date=row[6],
                title_en=row[7],
                source_page_numbers=article.source_page_numbers,
                status=row[8],
                current_step=row[9],
                automatic_failure_count=row[10],
                latest_error_summary=latest_error_summary,
            )
        )
    pagination = _build_pagination_view(page=page, page_size=page_size, total_count=total_count)
    if include_pagination:
        return cards, pagination
    return cards


def get_article_processing_filter_options_view(
    *,
    database_url: str,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
) -> ArticleProcessingFilterOptionsView:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        status_clauses, status_params = _build_article_processing_where_clauses(
            source=source,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
            step=step,
        )
        source_clauses, source_params = _build_article_processing_where_clauses(
            status=status,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
            step=step,
        )
        step_clauses, step_params = _build_article_processing_where_clauses(
            status=status,
            source=source,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
        )
        error_clauses, error_params = _build_article_processing_where_clauses(
            status=status,
            source=source,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
            step=step,
        )

        def fetch_distinct(column: str, clauses: list[str], params: list[object]) -> list[str]:
            query = f"""
            SELECT DISTINCT {column}
            FROM article_processing_runs r
            JOIN final_articles a
                ON a.article_id = r.article_id
            JOIN documents d
                ON d.document_key = a.document_key
            """
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
                query += f" AND {column} IS NOT NULL"
            else:
                query += f" WHERE {column} IS NOT NULL"
            query += f" ORDER BY {column} ASC"
            rows = connection.execute(query, tuple(params)).fetchall()
            return [row[0] for row in rows]

        return ArticleProcessingFilterOptionsView(
            statuses=fetch_distinct("r.status", status_clauses, status_params),
            sources=fetch_distinct("d.source_name", source_clauses, source_params),
            steps=fetch_distinct("r.current_step", step_clauses, step_params),
            error_messages=fetch_distinct("r.last_error_message", error_clauses, error_params),
        )
    finally:
        connection.close()


@overload
def list_article_card_views(
    *,
    database_url: str,
    source: str | None = None,
    tag: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    reading_status: str | None = None,
    processing_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    include_pagination: Literal[False] = False,
) -> ArticleCardList: ...


@overload
def list_article_card_views(
    *,
    database_url: str,
    source: str | None = None,
    tag: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    reading_status: str | None = None,
    processing_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    include_pagination: Literal[True],
) -> ArticleCardPage: ...


def list_article_card_views(
    *,
    database_url: str,
    source: str | None = None,
    tag: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    reading_status: str | None = None,
    processing_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    include_pagination: bool = False,
) -> ArticleCardList | ArticleCardPage:
    """List article cards.

    Default mode returns only the list to preserve existing callers.

    Set ``include_pagination=True`` to receive ``(items, pagination)``.
    Pagination normalizes non-positive ``page`` and ``page_size`` to ``1``.
    Empty result sets report ``total_pages == 0``.
    """
    page, page_size = _normalize_pagination(page=page, page_size=page_size)
    offset = (page - 1) * page_size
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        base_query, params = _build_article_card_filters(
            source=source,
            tag=tag,
            publication_date_from=publication_date_from,
            publication_date_to=publication_date_to,
            reading_status=reading_status,
            processing_status=processing_status,
        )
        total_count = connection.execute(
            "SELECT COUNT(*) " + base_query,
            tuple(params),
        ).fetchone()[0]
        query = """
        SELECT
            a.article_id,
            a.document_key,
            d.source_name,
            a.publication_date,
            a.title_en
        """ + base_query
        query += " ORDER BY a.publication_date DESC, a.article_order ASC LIMIT ? OFFSET ?"
        rows = connection.execute(query, tuple([*params, page_size, offset])).fetchall()
    finally:
        connection.close()

    cards = []
    for row in rows:
        title_zh = None
        summary_zh = None
        tags: list[str] = []
        processing_badges: list[str] = []
        reading_status = "english_fallback"
        try:
            enrichment = get_latest_article_enrichment(
                database_url=database_url,
                article_id=row[0],
            )
        except LookupError:
            enrichment = None
        if enrichment is not None:
            title_zh = enrichment.translated_title_zh
            summary_zh = enrichment.summary_zh
            tags = enrichment.tags
            reading_status = "ready"
            if enrichment.status == "partial":
                processing_badges.append("partial_enrichment")

        cards.append(
            ArticleCardView(
                article_id=row[0],
                document_key=row[1],
                source_name=row[2],
                publication_date=row[3],
                page_label="",
                title_en=row[4],
                title_zh=title_zh,
                summary_zh=summary_zh,
                tags=tags,
                hero_image_url=None,
                reading_status=reading_status,
                quality_flags=[],
                processing_badges=processing_badges,
            )
        )
    pagination = _build_pagination_view(page=page, page_size=page_size, total_count=total_count)
    if include_pagination:
        return cards, pagination
    return cards


def list_focus_tag_article_card_views(
    *,
    database_url: str,
    focus_tags: list[str],
) -> list[ArticleCardView]:
    normalized_tags = [tag.strip() for tag in focus_tags if tag.strip()]
    if not normalized_tags:
        return []

    seen_article_ids: set[str] = set()
    cards: list[ArticleCardView] = []
    for focus_tag in normalized_tags:
        tag_cards = list_article_card_views(
            database_url=database_url,
            tag=focus_tag,
        )
        for card in tag_cards:
            if card.article_id in seen_article_ids:
                continue
            seen_article_ids.add(card.article_id)
            cards.append(card)
    return cards
