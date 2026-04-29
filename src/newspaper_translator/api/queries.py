from dataclasses import dataclass
import sqlite3

from newspaper_translator.article_store import get_final_article, get_latest_article_enrichment
from newspaper_translator.database import sqlite_path_from_database_url


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
    hero_image_url: str | None
    quality: dict[str, object]
    processing: dict[str, object]


@dataclass(frozen=True)
class FilterOptionsView:
    sources: list[str]
    tags: list[str]


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
            """
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
            WHERE r.status IN ('partial', 'succeeded')
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
        hero_image_url=None,
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


def list_article_card_views(
    *,
    database_url: str,
    source: str | None = None,
    tag: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
) -> list[ArticleCardView]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        query = """
        SELECT
            a.article_id,
            a.document_key,
            d.source_name,
            a.publication_date,
            a.title_en
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
        """
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
        query += " ORDER BY a.publication_date DESC, a.article_order ASC"
        rows = connection.execute(query, tuple(params)).fetchall()
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
        for card in list_article_card_views(
            database_url=database_url,
            tag=focus_tag,
        ):
            if card.article_id in seen_article_ids:
                continue
            seen_article_ids.add(card.article_id)
            cards.append(card)
    return cards
