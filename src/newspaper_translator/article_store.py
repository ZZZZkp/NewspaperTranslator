from dataclasses import dataclass
import sqlite3
import uuid

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
                    title,
                    body_text,
                    continued_to_page,
                    continued_from_page,
                    is_continuation_candidate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fragment_id,
                    parse_run_id,
                    fragment.source_order,
                    fragment.title,
                    fragment.body_text,
                    fragment.continued_to_page,
                    fragment.continued_from_page,
                    int(bool(fragment.continued_to_page or fragment.continued_from_page)),
                ),
            )

        matcher_name = _get_parse_run(database_url=database_url, parse_run_id=parse_run_id).continuation_matcher_name
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
                    article_id,
                    parse_run_id,
                    document_key,
                    publication_date,
                    article.article_order,
                    article.primary_source_order,
                    article.source_fragment_count,
                    article.title,
                    article.body_text,
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
            title=row[3],
            body_text=row[4],
            continued_to_page=row[5],
            continued_from_page=row[6],
            is_continuation_candidate=bool(row[7]),
            created_at=row[8],
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
    finally:
        connection.close()
    return [_final_article_from_row(row) for row in rows]


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
    finally:
        connection.close()

    if row is None:
        raise LookupError(f"Final article not found: {article_id}")
    return _final_article_from_row(row)


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
) -> None:
    if translation_status == "succeeded":
        if not (translated_title_zh or "").strip() or not (translated_body_zh or "").strip():
            raise ValueError("Successful translation output requires Chinese title and body text")
    if summary_status == "succeeded" and not (summary_zh or "").strip():
        raise ValueError("Successful summary output requires non-empty summary_zh")
    if tagging_status == "succeeded" and not 3 <= len(tags) <= 8:
        raise ValueError("Successful tagging output must produce 3 to 8 tags")

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
                tagging_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enrichment_run_id,
                translated_title_zh,
                summary_zh,
                translated_body_zh,
                translation_status,
                summary_status,
                tagging_status,
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
                r.started_at,
                r.finished_at
            FROM article_enrichment_runs r
            LEFT JOIN article_enrichment_outputs o
                ON o.enrichment_run_id = r.enrichment_run_id
            WHERE r.article_id = ?
                AND r.status IN ('partial', 'succeeded')
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
        tags=[tag_row[0] for tag_row in tag_rows],
        started_at=row[14],
        finished_at=row[15],
    )


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


def _final_article_from_row(row) -> StoredFinalArticle:
    return StoredFinalArticle(
        article_id=row[0],
        parse_run_id=row[1],
        document_key=row[2],
        publication_date=row[3],
        article_order=row[4],
        primary_source_order=row[5],
        source_fragment_count=row[6],
        title_en=row[7],
        body_text_en=row[8],
        created_at=row[9],
    )
