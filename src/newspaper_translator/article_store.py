from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import re
import sqlite3
import uuid

from newspaper_translator.article_content import extract_local_image_paths_and_clean_text
from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.pdf import ParseResult


@dataclass(frozen=True)
class ParseRun:
    parse_run_id: str
    document_key: str
    status: str
    parser_name: str
    parser_version: str
    publication_date: str
    continuation_matcher_name: str
    continuation_matcher_version: str
    mineru_batch_id: str | None
    mineru_file_id: str | None
    markdown_path: str | None
    started_at: str
    finished_at: str | None
    error_message: str | None


@dataclass(frozen=True)
class StoredArticleFragment:
    fragment_id: str
    parse_run_id: str
    source_order: int
    page_number: int
    title: str
    body_text: str
    continued_to_page: str
    continued_from_page: str
    is_continuation_candidate: bool
    created_at: str


@dataclass(frozen=True)
class StoredContinuationMatch:
    match_id: str
    parse_run_id: str
    front_fragment_id: str | None
    back_fragment_id: str | None
    matcher_name: str
    matcher_raw_response: str
    decision_status: str
    decision_reason: str
    created_at: str


@dataclass(frozen=True)
class StoredFinalArticle:
    article_id: str
    parse_run_id: str
    document_key: str
    publication_date: str
    article_order: int
    primary_source_order: int
    source_fragment_count: int
    title_en: str
    body_text_en: str
    created_at: str
    source_page_numbers: list[int] = field(default_factory=list)
    article_key: str = ""


@dataclass(frozen=True)
class StoredArticleImage:
    article_id: str
    image_path: str
    image_order: int


@dataclass(frozen=True)
class ArticleEnrichmentRun:
    enrichment_run_id: str
    article_id: str
    parse_run_id: str
    status: str
    provider_name: str
    model_name: str
    prompt_version: str
    input_hash: str
    started_at: str
    finished_at: str | None
    error_message: str | None


@dataclass(frozen=True)
class LatestArticleEnrichment:
    enrichment_run_id: str
    article_id: str
    parse_run_id: str
    status: str
    provider_name: str
    model_name: str
    prompt_version: str
    input_hash: str
    translated_title_zh: str | None
    summary_zh: str | None
    translated_body_zh: str | None
    translation_status: str
    summary_status: str
    tagging_status: str
    content_type: str
    classification_reason: str
    tags: list[str]
    started_at: str
    finished_at: str | None


def create_parse_run(
    *,
    database_url: str,
    document_key: str,
    parser_name: str,
    parser_version: str,
    publication_date: str,
    continuation_matcher_name: str = "",
    continuation_matcher_version: str = "",
) -> ParseRun:
    parse_run_id = str(uuid.uuid4())
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO parse_runs (
                parse_run_id,
                document_key,
                status,
                parser_name,
                parser_version,
                publication_date,
                continuation_matcher_name,
                continuation_matcher_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parse_run_id,
                document_key,
                "running",
                parser_name,
                parser_version,
                publication_date,
                continuation_matcher_name,
                continuation_matcher_version,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return _get_parse_run(database_url=database_url, parse_run_id=parse_run_id)


def update_parse_run_source_artifacts(
    *,
    database_url: str,
    parse_run_id: str,
    mineru_batch_id: str | None,
    mineru_file_id: str | None,
    markdown_path: str | None,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE parse_runs
            SET
                mineru_batch_id = ?,
                mineru_file_id = ?,
                markdown_path = ?
            WHERE parse_run_id = ?
            """,
            (
                mineru_batch_id,
                mineru_file_id,
                markdown_path,
                parse_run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def record_parse_run_result(
    *,
    database_url: str,
    parse_run_id: str,
    parse_result: ParseResult,
    document_key: str,
    publication_date: str,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        parse_run = _get_parse_run(database_url=database_url, parse_run_id=parse_run_id)
        markdown_base_dir = None
        if parse_run.markdown_path:
            markdown_base_dir = Path(parse_run.markdown_path).resolve().parent

        fragment_ids_by_source_order: dict[int, str] = {}
        for fragment in parse_result.fragments:
            fragment_id = str(uuid.uuid4())
            fragment_ids_by_source_order[fragment.source_order] = fragment_id
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
                    fragment_id,
                    parse_run_id,
                    fragment.source_order,
                    getattr(fragment, "page_number", 0),
                    fragment.title,
                    fragment.body_text,
                    fragment.continued_to_page,
                    fragment.continued_from_page,
                    int(bool(fragment.continued_to_page or fragment.continued_from_page)),
                ),
            )

        matcher_name = parse_run.continuation_matcher_name
        for decision in parse_result.match_decisions:
            connection.execute(
                """
                INSERT INTO continuation_matches (
                    match_id,
                    parse_run_id,
                    front_fragment_id,
                    back_fragment_id,
                    matcher_name,
                    matcher_raw_response,
                    decision_status,
                    decision_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    parse_run_id,
                    fragment_ids_by_source_order.get(decision.front_source_order),
                    fragment_ids_by_source_order.get(decision.back_source_order),
                    matcher_name,
                    decision.matcher_raw_response,
                    decision.decision_status,
                    decision.decision_reason,
                ),
            )

        for article in parse_result.articles:
            article_id = str(uuid.uuid4())
            article_key = _resolve_article_key(
                connection=connection,
                parse_run_id=parse_run_id,
                document_key=document_key,
                title_en=article.title,
                body_text_en=article.body_text,
                source_page_numbers=[
                    getattr(parse_result.fragments[source_fragment.source_order - 1], "page_number", 0)
                    for source_fragment in article.source_fragments
                ],
            )
            image_paths, cleaned_body_text = extract_local_image_paths_and_clean_text(
                article.body_text,
                base_dir=markdown_base_dir,
            )
            connection.execute(
                """
                INSERT INTO final_articles (
                    article_id,
                    article_key,
                    parse_run_id,
                    document_key,
                    publication_date,
                    article_order,
                    primary_source_order,
                    source_fragment_count,
                    title_en,
                    body_text_en
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    article_key,
                    parse_run_id,
                    document_key,
                    publication_date,
                    article.article_order,
                    article.primary_source_order,
                    article.source_fragment_count,
                    article.title,
                    cleaned_body_text,
                ),
            )
            for image_order, image_path in enumerate(image_paths, start=1):
                connection.execute(
                    """
                    INSERT INTO article_images (
                        article_image_id,
                        article_id,
                        image_path,
                        image_order
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        article_id,
                        image_path,
                        image_order,
                    ),
                )
            for source_fragment in article.source_fragments:
                connection.execute(
                    """
                    INSERT INTO final_article_fragments (
                        article_id,
                        fragment_id,
                        fragment_role,
                        sequence_index
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        article_id,
                        fragment_ids_by_source_order[source_fragment.source_order],
                        source_fragment.fragment_role,
                        source_fragment.sequence_index,
                    ),
                )

        connection.commit()
    finally:
        connection.close()


def finalize_parse_run(
    *,
    database_url: str,
    parse_run_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE parse_runs
            SET
                status = ?,
                error_message = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE parse_run_id = ?
            """,
            (
                status,
                error_message,
                parse_run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def list_parse_runs(*, database_url: str, document_key: str) -> list[ParseRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                parse_run_id,
                document_key,
                status,
                parser_name,
                parser_version,
                publication_date,
                continuation_matcher_name,
                continuation_matcher_version,
                mineru_batch_id,
                mineru_file_id,
                markdown_path,
                started_at,
                finished_at,
                error_message
            FROM parse_runs
            WHERE document_key = ?
            ORDER BY started_at DESC, rowid DESC
            """,
            (document_key,),
        ).fetchall()
    finally:
        connection.close()
    return [_parse_run_from_row(row) for row in rows]


def list_parse_run_fragments(
    *,
    database_url: str,
    parse_run_id: str,
) -> list[StoredArticleFragment]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                fragment_id,
                parse_run_id,
                source_order,
                page_number,
                title,
                body_text,
                continued_to_page,
                continued_from_page,
                is_continuation_candidate,
                created_at
            FROM article_fragments
            WHERE parse_run_id = ?
            ORDER BY source_order ASC
            """,
            (parse_run_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        StoredArticleFragment(
            fragment_id=row[0],
            parse_run_id=row[1],
            source_order=row[2],
            page_number=row[3],
            title=row[4],
            body_text=row[5],
            continued_to_page=row[6],
            continued_from_page=row[7],
            is_continuation_candidate=bool(row[8]),
            created_at=row[9],
        )
        for row in rows
    ]


def list_parse_run_continuation_matches(
    *,
    database_url: str,
    parse_run_id: str,
) -> list[StoredContinuationMatch]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                match_id,
                parse_run_id,
                front_fragment_id,
                back_fragment_id,
                matcher_name,
                matcher_raw_response,
                decision_status,
                decision_reason,
                created_at
            FROM continuation_matches
            WHERE parse_run_id = ?
            ORDER BY rowid ASC
            """,
            (parse_run_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        StoredContinuationMatch(
            match_id=row[0],
            parse_run_id=row[1],
            front_fragment_id=row[2],
            back_fragment_id=row[3],
            matcher_name=row[4],
            matcher_raw_response=row[5],
            decision_status=row[6],
            decision_reason=row[7],
            created_at=row[8],
        )
        for row in rows
    ]


def list_parse_run_final_articles(
    *,
    database_url: str,
    parse_run_id: str,
) -> list[StoredFinalArticle]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                article_id,
                article_key,
                parse_run_id,
                document_key,
                publication_date,
                article_order,
                primary_source_order,
                source_fragment_count,
                title_en,
                body_text_en,
                created_at
            FROM final_articles
            WHERE parse_run_id = ?
            ORDER BY article_order ASC
            """,
            (parse_run_id,),
        ).fetchall()
        articles = [
            _final_article_from_row(
                row,
                source_page_numbers=_list_article_source_page_numbers(
                    connection=connection,
                    article_id=row[0],
                ),
            )
            for row in rows
        ]
    finally:
        connection.close()
    return articles


def list_latest_document_articles(
    *,
    database_url: str,
    document_key: str,
) -> list[StoredFinalArticle]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT parse_run_id
            FROM parse_runs
            WHERE document_key = ? AND status = 'succeeded'
            ORDER BY finished_at DESC, rowid DESC
            LIMIT 1
            """,
            (document_key,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return []
    return list_parse_run_final_articles(
        database_url=database_url,
        parse_run_id=row[0],
    )


def get_final_article(
    *,
    database_url: str,
    article_id: str,
) -> StoredFinalArticle:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                article_id,
                article_key,
                parse_run_id,
                document_key,
                publication_date,
                article_order,
                primary_source_order,
                source_fragment_count,
                title_en,
                body_text_en,
                created_at
            FROM final_articles
            WHERE article_id = ?
            """,
            (article_id,),
        ).fetchone()
        if row is None:
            article = None
        else:
            article = _final_article_from_row(
                row,
                source_page_numbers=_list_article_source_page_numbers(
                    connection=connection,
                    article_id=article_id,
                ),
            )
    finally:
        connection.close()

    if article is None:
        raise LookupError(f"Final article not found: {article_id}")
    return article


def list_article_images(
    *,
    database_url: str,
    article_id: str,
) -> list[StoredArticleImage]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT article_id, image_path, image_order
            FROM article_images
            WHERE article_id = ?
            ORDER BY image_order ASC
            """,
            (article_id,),
        ).fetchall()
    finally:
        connection.close()

    return [
        StoredArticleImage(
            article_id=row[0],
            image_path=row[1],
            image_order=row[2],
        )
        for row in rows
    ]


def create_article_enrichment_run(
    *,
    database_url: str,
    article_id: str,
    parse_run_id: str,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    input_hash: str,
) -> ArticleEnrichmentRun:
    enrichment_run_id = str(uuid.uuid4())
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO article_enrichment_runs (
                enrichment_run_id,
                article_id,
                parse_run_id,
                status,
                provider_name,
                model_name,
                prompt_version,
                input_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enrichment_run_id,
                article_id,
                parse_run_id,
                "running",
                provider_name,
                model_name,
                prompt_version,
                input_hash,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return _get_article_enrichment_run(
        database_url=database_url,
        enrichment_run_id=enrichment_run_id,
    )


def get_article_enrichment_run(
    *,
    database_url: str,
    enrichment_run_id: str,
) -> ArticleEnrichmentRun:
    return _get_article_enrichment_run(
        database_url=database_url,
        enrichment_run_id=enrichment_run_id,
    )


def record_article_enrichment_outputs(
    *,
    database_url: str,
    enrichment_run_id: str,
    translated_title_zh: str | None,
    summary_zh: str | None,
    translated_body_zh: str | None,
    translation_status: str,
    summary_status: str,
    tagging_status: str,
    tags: list[str],
    content_type: str = "article",
    classification_reason: str = "",
) -> None:
    if translation_status == "succeeded":
        if not (translated_title_zh or "").strip() or not (translated_body_zh or "").strip():
            raise ValueError("Successful translation output requires Chinese title and body text")
    if summary_status == "succeeded" and not (summary_zh or "").strip():
        raise ValueError("Successful summary output requires non-empty summary_zh")
    if tagging_status == "succeeded" and not 3 <= len(tags) <= 8:
        raise ValueError("Successful tagging output must produce 3 to 8 tags")
    if content_type not in ("article", "advertisement", "uncertain"):
        raise ValueError(
            f"Unsupported content_type for enrichment output: {content_type!r}"
        )

    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO article_enrichment_outputs (
                enrichment_run_id,
                translated_title_zh,
                summary_zh,
                translated_body_zh,
                translation_status,
                summary_status,
                tagging_status,
                content_type,
                classification_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enrichment_run_id,
                translated_title_zh,
                summary_zh,
                translated_body_zh,
                translation_status,
                summary_status,
                tagging_status,
                content_type,
                classification_reason,
            ),
        )
        for index, tag in enumerate(tags, start=1):
            connection.execute(
                """
                INSERT INTO article_tags (
                    article_tag_id,
                    enrichment_run_id,
                    tag_text,
                    tag_order
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    enrichment_run_id,
                    tag,
                    index,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def finalize_article_enrichment_run(
    *,
    database_url: str,
    enrichment_run_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE article_enrichment_runs
            SET
                status = ?,
                error_message = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE enrichment_run_id = ?
            """,
            (
                status,
                error_message,
                enrichment_run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_latest_article_enrichment(
    *,
    database_url: str,
    article_id: str,
) -> LatestArticleEnrichment:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                r.enrichment_run_id,
                r.article_id,
                r.parse_run_id,
                r.status,
                r.provider_name,
                r.model_name,
                r.prompt_version,
                r.input_hash,
                o.translated_title_zh,
                o.summary_zh,
                o.translated_body_zh,
                o.translation_status,
                o.summary_status,
                o.tagging_status,
                o.content_type,
                o.classification_reason,
                r.started_at,
                r.finished_at
            FROM article_enrichment_runs r
            LEFT JOIN article_enrichment_outputs o
                ON o.enrichment_run_id = r.enrichment_run_id
            WHERE r.article_id = ?
                AND r.status IN ('partial', 'succeeded', 'skipped_advertisement')
            ORDER BY r.finished_at DESC, r.rowid DESC
            LIMIT 1
            """,
            (article_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"No usable enrichment run found for article: {article_id}")
        tag_rows = connection.execute(
            """
            SELECT tag_text
            FROM article_tags
            WHERE enrichment_run_id = ?
            ORDER BY tag_order ASC
            """,
            (row[0],),
        ).fetchall()
    finally:
        connection.close()

    return LatestArticleEnrichment(
        enrichment_run_id=row[0],
        article_id=row[1],
        parse_run_id=row[2],
        status=row[3],
        provider_name=row[4],
        model_name=row[5],
        prompt_version=row[6],
        input_hash=row[7],
        translated_title_zh=row[8],
        summary_zh=row[9],
        translated_body_zh=row[10],
        translation_status=row[11],
        summary_status=row[12],
        tagging_status=row[13],
        content_type=row[14] if row[14] is not None else "article",
        classification_reason=row[15] if row[15] is not None else "",
        tags=[tag_row[0] for tag_row in tag_rows],
        started_at=row[16],
        finished_at=row[17],
    )


def find_successful_article_enrichment_by_article_key_and_input_hash(
    *,
    database_url: str,
    article_key: str,
    input_hash: str,
) -> ArticleEnrichmentRun | None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                r.enrichment_run_id,
                r.article_id,
                r.parse_run_id,
                r.status,
                r.provider_name,
                r.model_name,
                r.prompt_version,
                r.input_hash,
                r.started_at,
                r.finished_at,
                r.error_message
            FROM article_enrichment_runs r
            JOIN final_articles a
                ON a.article_id = r.article_id
            WHERE a.article_key = ?
              AND r.input_hash = ?
              AND r.status = 'succeeded'
            ORDER BY r.finished_at DESC, r.rowid DESC
            LIMIT 1
            """,
            (
                article_key,
                input_hash,
            ),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return _article_enrichment_run_from_row(row)


def _get_parse_run(*, database_url: str, parse_run_id: str) -> ParseRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                parse_run_id,
                document_key,
                status,
                parser_name,
                parser_version,
                publication_date,
                continuation_matcher_name,
                continuation_matcher_version,
                mineru_batch_id,
                mineru_file_id,
                markdown_path,
                started_at,
                finished_at,
                error_message
            FROM parse_runs
            WHERE parse_run_id = ?
            """,
            (parse_run_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"Parse run not found: {parse_run_id}")
    return _parse_run_from_row(row)


def _get_article_enrichment_run(
    *,
    database_url: str,
    enrichment_run_id: str,
) -> ArticleEnrichmentRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                enrichment_run_id,
                article_id,
                parse_run_id,
                status,
                provider_name,
                model_name,
                prompt_version,
                input_hash,
                started_at,
                finished_at,
                error_message
            FROM article_enrichment_runs
            WHERE enrichment_run_id = ?
            """,
            (enrichment_run_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"Article enrichment run not found: {enrichment_run_id}")
    return _article_enrichment_run_from_row(row)


def _parse_run_from_row(row) -> ParseRun:
    return ParseRun(
        parse_run_id=row[0],
        document_key=row[1],
        status=row[2],
        parser_name=row[3],
        parser_version=row[4],
        publication_date=row[5],
        continuation_matcher_name=row[6],
        continuation_matcher_version=row[7],
        mineru_batch_id=row[8],
        mineru_file_id=row[9],
        markdown_path=row[10],
        started_at=row[11],
        finished_at=row[12],
        error_message=row[13],
    )


def _article_enrichment_run_from_row(row) -> ArticleEnrichmentRun:
    return ArticleEnrichmentRun(
        enrichment_run_id=row[0],
        article_id=row[1],
        parse_run_id=row[2],
        status=row[3],
        provider_name=row[4],
        model_name=row[5],
        prompt_version=row[6],
        input_hash=row[7],
        started_at=row[8],
        finished_at=row[9],
        error_message=row[10],
    )


def _list_article_source_page_numbers(*, connection, article_id: str) -> list[int]:
    rows = connection.execute(
        """
        SELECT DISTINCT f.page_number
        FROM final_article_fragments faf
        JOIN article_fragments f
            ON f.fragment_id = faf.fragment_id
        WHERE faf.article_id = ?
        ORDER BY f.page_number ASC, faf.sequence_index ASC
        """,
        (article_id,),
    ).fetchall()
    return [row[0] for row in rows]


def _resolve_article_key(
    *,
    connection,
    parse_run_id: str,
    document_key: str,
    title_en: str,
    body_text_en: str,
    source_page_numbers: list[int],
) -> str:
    candidate_rows = connection.execute(
        """
        SELECT article_id, article_key, title_en, body_text_en
        FROM final_articles
        WHERE document_key = ?
          AND parse_run_id <> ?
        ORDER BY created_at DESC, rowid DESC
        """,
        (document_key, parse_run_id),
    ).fetchall()
    normalized_title = _normalize_identity_text(title_en)
    normalized_opening = _normalize_identity_text(_article_opening(body_text_en))
    source_page_number_set = {page for page in source_page_numbers if page > 0}

    best_match_key = ""
    best_match_score = 0.0
    for candidate_row in candidate_rows:
        candidate_pages = set(
            _list_article_source_page_numbers(
                connection=connection,
                article_id=candidate_row[0],
            )
        )
        if source_page_number_set and not candidate_pages.intersection(source_page_number_set):
            continue

        title_similarity = _normalized_similarity(
            normalized_title,
            _normalize_identity_text(candidate_row[2]),
        )
        opening_similarity = _normalized_similarity(
            normalized_opening,
            _normalize_identity_text(_article_opening(candidate_row[3])),
        )
        match_score = max(title_similarity, opening_similarity)
        if match_score >= 0.9 and match_score > best_match_score:
            best_match_key = candidate_row[1]
            best_match_score = match_score

    if best_match_key:
        return best_match_key
    return str(uuid.uuid4())


def _normalize_identity_text(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold()).strip()


def _normalized_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def _article_opening(body_text: str, *, max_chars: int = 160) -> str:
    return body_text[:max_chars]


def _final_article_from_row(row, *, source_page_numbers: list[int]) -> StoredFinalArticle:
    return StoredFinalArticle(
        article_id=row[0],
        article_key=row[1],
        parse_run_id=row[2],
        document_key=row[3],
        publication_date=row[4],
        article_order=row[5],
        primary_source_order=row[6],
        source_fragment_count=row[7],
        title_en=row[8],
        body_text_en=row[9],
        source_page_numbers=source_page_numbers,
        created_at=row[10],
    )
