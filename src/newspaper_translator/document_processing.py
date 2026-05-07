from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import uuid

from newspaper_translator.article_enrichment import build_article_input_hash, enrich_article
from newspaper_translator.article_pipeline import persist_document_articles
from newspaper_translator.article_store import get_final_article, list_latest_document_articles
from newspaper_translator.logging_utils import format_log_event
from newspaper_translator.database import sqlite_path_from_database_url


@dataclass(frozen=True)
class ProcessingTickResult:
    scheduler_run_id: str | None
    did_work: bool
    selected_document_count: int
    completed_document_count: int
    failed_document_count: int


@dataclass(frozen=True)
class DrainResult:
    did_work: bool
    selected_count: int
    completed_count: int
    failed_count: int
    error_messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchedulerRun:
    scheduler_run_id: str
    trigger_type: str
    status: str
    started_at: str
    finished_at: str | None
    import_run_id: str | None
    selected_document_count: int
    completed_document_count: int
    failed_document_count: int
    error_message: str | None


@dataclass(frozen=True)
class DocumentProcessingRun:
    processing_run_id: str
    scheduler_run_id: str | None
    document_key: str
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


@dataclass(frozen=True)
class ArticleProcessingRun:
    article_processing_run_id: str
    article_key: str
    article_id: str
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


def create_scheduler_run(*, database_url: str, trigger_type: str) -> SchedulerRun:
    scheduler_run_id = str(uuid.uuid4())
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO scheduler_runs (
                scheduler_run_id,
                trigger_type,
                status
            ) VALUES (?, ?, ?)
            """,
            (
                scheduler_run_id,
                trigger_type,
                "running",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return get_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run_id,
    )


def finalize_scheduler_run(
    *,
    database_url: str,
    scheduler_run_id: str,
    status: str,
    import_run_id: str | None = None,
    selected_document_count: int = 0,
    completed_document_count: int = 0,
    failed_document_count: int = 0,
    error_message: str | None = None,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE scheduler_runs
            SET
                status = ?,
                finished_at = CURRENT_TIMESTAMP,
                import_run_id = ?,
                selected_document_count = ?,
                completed_document_count = ?,
                failed_document_count = ?,
                error_message = ?
            WHERE scheduler_run_id = ?
            """,
            (
                status,
                import_run_id,
                selected_document_count,
                completed_document_count,
                failed_document_count,
                error_message,
                scheduler_run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_scheduler_run(*, database_url: str, scheduler_run_id: str) -> SchedulerRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                scheduler_run_id,
                trigger_type,
                status,
                started_at,
                finished_at,
                import_run_id,
                selected_document_count,
                completed_document_count,
                failed_document_count,
                error_message
            FROM scheduler_runs
            WHERE scheduler_run_id = ?
            """,
            (scheduler_run_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise LookupError(f"Scheduler run not found: {scheduler_run_id}")

    return _row_to_scheduler_run(row)


def get_latest_scheduler_run(*, database_url: str) -> SchedulerRun | None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                scheduler_run_id,
                trigger_type,
                status,
                started_at,
                finished_at,
                import_run_id,
                selected_document_count,
                completed_document_count,
                failed_document_count,
                error_message
            FROM scheduler_runs
            ORDER BY started_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return _row_to_scheduler_run(row)


def create_document_processing_run(
    *,
    database_url: str,
    document_key: str,
) -> DocumentProcessingRun:
    processing_run_id = str(uuid.uuid4())
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO document_processing_runs (
                processing_run_id,
                document_key,
                status,
                current_step
            ) VALUES (?, ?, ?, ?)
            """,
            (
                processing_run_id,
                document_key,
                "pending",
                "parse_persist",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    if cursor.rowcount == 0:
        return get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        )
    return get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )


def create_article_processing_run(
    *,
    database_url: str,
    article_id: str,
) -> ArticleProcessingRun:
    article_processing_run_id = str(uuid.uuid4())
    article = get_final_article(
        database_url=database_url,
        article_id=article_id,
    )
    article_key = article.article_key
    input_hash = build_article_input_hash(article)
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        existing_row = connection.execute(
            """
            SELECT status, last_success_input_hash
            FROM article_processing_runs
            WHERE article_key = ?
            """,
            (article_key,),
        ).fetchone()
        if existing_row is None:
            connection.execute(
                """
                INSERT INTO article_processing_runs (
                    article_processing_run_id,
                    article_key,
                    article_id,
                    status,
                    current_step
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    article_processing_run_id,
                    article_key,
                    article_id,
                    "pending",
                    "enrich",
                ),
            )
        else:
            current_status = existing_row[0]
            last_success_input_hash = existing_row[1]
            if current_status == "manual_retry_requested":
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        article_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (
                        article_id,
                        article_key,
                    ),
                )
            elif last_success_input_hash == input_hash:
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        article_id = ?,
                        status = 'succeeded',
                        current_step = 'completed',
                        locked_by = NULL,
                        lock_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (
                        article_id,
                        article_key,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE article_processing_runs
                    SET
                        article_id = ?,
                        status = 'pending',
                        current_step = 'enrich',
                        automatic_failure_count = 0,
                        last_error_message = NULL,
                        last_attempt_started_at = NULL,
                        last_attempt_finished_at = NULL,
                        locked_by = NULL,
                        lock_expires_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE article_key = ?
                    """,
                    (
                        article_id,
                        article_key,
                    ),
                )
        connection.commit()
    finally:
        connection.close()

    return get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )


def claim_document_processing_run(
    *,
    database_url: str,
    document_key: str,
    locked_by: str,
    lock_timeout_seconds: int,
    scheduler_run_id: str | None = None,
) -> DocumentProcessingRun | None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        cursor = connection.execute(
            """
            UPDATE document_processing_runs
            SET
                scheduler_run_id = ?,
                status = ?,
                locked_by = ?,
                lock_expires_at = datetime(CURRENT_TIMESTAMP, '+' || ? || ' seconds'),
                last_attempt_started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE document_key = ?
              AND status IN ('pending', 'failed_retryable', 'manual_retry_requested')
              AND (
                    locked_by IS NULL
                    OR lock_expires_at IS NULL
                    OR lock_expires_at <= CURRENT_TIMESTAMP
              )
            """,
            (
                scheduler_run_id,
                "running",
                locked_by,
                lock_timeout_seconds,
                document_key,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    if cursor.rowcount == 0:
        return None
    return get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )


def claim_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    locked_by: str,
    lock_timeout_seconds: int,
) -> ArticleProcessingRun | None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        cursor = connection.execute(
            """
            UPDATE article_processing_runs
            SET
                status = 'running',
                locked_by = ?,
                lock_expires_at = datetime(CURRENT_TIMESTAMP, '+' || ? || ' seconds'),
                last_attempt_started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_key = ?
              AND status IN ('pending', 'failed_retryable', 'manual_retry_requested')
              AND (
                    locked_by IS NULL
                    OR lock_expires_at IS NULL
                    OR lock_expires_at <= CURRENT_TIMESTAMP
              )
            """,
            (
                locked_by,
                lock_timeout_seconds,
                article_key,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    if cursor.rowcount == 0:
        return None
    return get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )


def get_document_processing_run(
    *,
    database_url: str,
    document_key: str,
) -> DocumentProcessingRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                processing_run_id,
                scheduler_run_id,
                document_key,
                status,
                current_step,
                automatic_failure_count,
                last_failure_step,
                last_error_message,
                last_attempt_started_at,
                last_attempt_finished_at,
                locked_by,
                lock_expires_at,
                created_at,
                updated_at
            FROM document_processing_runs
            WHERE document_key = ?
            """,
            (document_key,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise LookupError(f"Document processing run not found: {document_key}")

    return DocumentProcessingRun(
        processing_run_id=row[0],
        scheduler_run_id=row[1],
        document_key=row[2],
        status=row[3],
        current_step=row[4],
        automatic_failure_count=row[5],
        last_failure_step=row[6],
        last_error_message=row[7],
        last_attempt_started_at=row[8],
        last_attempt_finished_at=row[9],
        locked_by=row[10],
        lock_expires_at=row[11],
        created_at=row[12],
        updated_at=row[13],
    )


def get_article_processing_run(
    *,
    database_url: str,
    article_key: str,
) -> ArticleProcessingRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                article_processing_run_id,
                article_key,
                article_id,
                status,
                current_step,
                automatic_failure_count,
                last_error_message,
                last_success_input_hash,
                last_attempt_started_at,
                last_attempt_finished_at,
                locked_by,
                lock_expires_at,
                created_at,
                updated_at
            FROM article_processing_runs
            WHERE article_key = ?
            """,
            (article_key,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise LookupError(f"Article processing run not found: {article_key}")
    return _row_to_article_processing_run(row)


def list_eligible_document_processing_runs(
    *,
    database_url: str,
    limit: int,
) -> list[DocumentProcessingRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                processing_run_id,
                scheduler_run_id,
                document_key,
                status,
                current_step,
                automatic_failure_count,
                last_failure_step,
                last_error_message,
                last_attempt_started_at,
                last_attempt_finished_at,
                locked_by,
                lock_expires_at,
                created_at,
                updated_at
            FROM document_processing_runs
            WHERE status IN ('manual_retry_requested', 'pending', 'failed_retryable')
            ORDER BY
                CASE status
                    WHEN 'manual_retry_requested' THEN 0
                    WHEN 'pending' THEN 1
                    WHEN 'failed_retryable' THEN 2
                    ELSE 3
                END,
                updated_at ASC,
                created_at ASC,
                rowid ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()

    return [
        _row_to_document_processing_run(row)
        for row in rows
    ]


def list_eligible_article_processing_runs(
    *,
    database_url: str,
    limit: int,
) -> list[ArticleProcessingRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                article_processing_run_id,
                article_key,
                article_id,
                status,
                current_step,
                automatic_failure_count,
                last_error_message,
                last_success_input_hash,
                last_attempt_started_at,
                last_attempt_finished_at,
                locked_by,
                lock_expires_at,
                created_at,
                updated_at
            FROM article_processing_runs
            WHERE status IN ('manual_retry_requested', 'pending', 'failed_retryable')
            ORDER BY
                CASE status
                    WHEN 'manual_retry_requested' THEN 0
                    WHEN 'pending' THEN 1
                    WHEN 'failed_retryable' THEN 2
                    ELSE 3
                END,
                updated_at ASC,
                created_at ASC,
                rowid ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()

    return [_row_to_article_processing_run(row) for row in rows]


def list_document_processing_runs(
    *,
    database_url: str,
    limit: int,
    status: str | None = None,
) -> list[DocumentProcessingRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        if status:
            rows = connection.execute(
                """
                SELECT
                    processing_run_id,
                    scheduler_run_id,
                    document_key,
                    status,
                    current_step,
                    automatic_failure_count,
                    last_failure_step,
                    last_error_message,
                    last_attempt_started_at,
                    last_attempt_finished_at,
                    locked_by,
                    lock_expires_at,
                    created_at,
                    updated_at
                FROM document_processing_runs
                WHERE status = ?
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT
                    processing_run_id,
                    scheduler_run_id,
                    document_key,
                    status,
                    current_step,
                    automatic_failure_count,
                    last_failure_step,
                    last_error_message,
                    last_attempt_started_at,
                    last_attempt_finished_at,
                    locked_by,
                    lock_expires_at,
                    created_at,
                    updated_at
                FROM document_processing_runs
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        connection.close()

    return [_row_to_document_processing_run(row) for row in rows]


def list_article_processing_runs(
    *,
    database_url: str,
    limit: int,
    status: str | None = None,
) -> list[ArticleProcessingRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        if status:
            rows = connection.execute(
                """
                SELECT
                    article_processing_run_id,
                    article_key,
                    article_id,
                    status,
                    current_step,
                    automatic_failure_count,
                    last_error_message,
                    last_success_input_hash,
                    last_attempt_started_at,
                    last_attempt_finished_at,
                    locked_by,
                    lock_expires_at,
                    created_at,
                    updated_at
                FROM article_processing_runs
                WHERE status = ?
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT
                    article_processing_run_id,
                    article_key,
                    article_id,
                    status,
                    current_step,
                    automatic_failure_count,
                    last_error_message,
                    last_success_input_hash,
                    last_attempt_started_at,
                    last_attempt_finished_at,
                    locked_by,
                    lock_expires_at,
                    created_at,
                    updated_at
                FROM article_processing_runs
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        connection.close()

    return [_row_to_article_processing_run(row) for row in rows]


def fail_document_processing_run(
    *,
    database_url: str,
    document_key: str,
    failed_step: str,
    error_message: str,
    automatic_failure_limit: int = 2,
    log_event=None,
) -> DocumentProcessingRun:
    stored_run = get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )
    new_failure_count = stored_run.automatic_failure_count + 1
    new_status = (
        "failed_terminal"
        if new_failure_count >= automatic_failure_limit
        else "failed_retryable"
    )

    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE document_processing_runs
            SET
                status = ?,
                current_step = ?,
                automatic_failure_count = ?,
                last_failure_step = ?,
                last_error_message = ?,
                last_attempt_finished_at = CURRENT_TIMESTAMP,
                locked_by = NULL,
                lock_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE document_key = ?
            """,
            (
                new_status,
                failed_step,
                new_failure_count,
                failed_step,
                error_message,
                document_key,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    updated_run = get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )
    _log_event(
        log_event,
        event="document.marked_failed",
        details={
            "document_key": document_key,
            "failed_step": failed_step,
            "status": updated_run.status,
            "automatic_failure_count": updated_run.automatic_failure_count,
            "error_message": error_message,
        },
    )
    return updated_run


def fail_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    failed_step: str,
    error_message: str,
    automatic_failure_limit: int = 2,
) -> ArticleProcessingRun:
    stored_run = get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )
    new_failure_count = stored_run.automatic_failure_count + 1
    new_status = (
        "failed_terminal"
        if new_failure_count >= automatic_failure_limit
        else "failed_retryable"
    )
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE article_processing_runs
            SET
                status = ?,
                current_step = ?,
                automatic_failure_count = ?,
                last_error_message = ?,
                last_attempt_finished_at = CURRENT_TIMESTAMP,
                locked_by = NULL,
                lock_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_key = ?
            """,
            (
                new_status,
                failed_step,
                new_failure_count,
                error_message,
                article_key,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )


def request_manual_document_retry(
    *,
    database_url: str,
    document_key: str,
    log_event=None,
) -> DocumentProcessingRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE document_processing_runs
            SET
                status = 'manual_retry_requested',
                locked_by = NULL,
                lock_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE document_key = ?
            """,
            (document_key,),
        )
        connection.commit()
    finally:
        connection.close()

    updated_run = get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )
    _log_event(
        log_event,
        event="document.manual_retry_requested",
        details={
            "document_key": document_key,
            "status": updated_run.status,
        },
    )
    return updated_run


def request_manual_article_retry(
    *,
    database_url: str,
    article_key: str,
) -> ArticleProcessingRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE article_processing_runs
            SET
                status = 'manual_retry_requested',
                locked_by = NULL,
                lock_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_key = ?
            """,
            (article_key,),
        )
        connection.commit()
    finally:
        connection.close()
    return get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )


def succeed_document_processing_run(
    *,
    database_url: str,
    document_key: str,
) -> DocumentProcessingRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE document_processing_runs
            SET
                status = 'succeeded',
                current_step = 'completed',
                last_attempt_finished_at = CURRENT_TIMESTAMP,
                locked_by = NULL,
                lock_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE document_key = ?
            """,
            (document_key,),
        )
        connection.commit()
    finally:
        connection.close()

    return get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )


def succeed_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    last_success_input_hash: str,
) -> ArticleProcessingRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE article_processing_runs
            SET
                status = 'succeeded',
                current_step = 'completed',
                last_success_input_hash = ?,
                last_attempt_finished_at = CURRENT_TIMESTAMP,
                locked_by = NULL,
                lock_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE article_key = ?
            """,
            (
                last_success_input_hash,
                article_key,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return get_article_processing_run(
        database_url=database_url,
        article_key=article_key,
    )


def process_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    locked_by: str,
    translator,
    summarizer_tagger,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    lock_timeout_seconds: int = 600,
    automatic_failure_limit: int = 2,
) -> ArticleProcessingRun:
    existing_run = None
    try:
        existing_run = get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        )
    except LookupError:
        existing_run = None
    claimed_run = claim_article_processing_run(
        database_url=database_url,
        article_key=article_key,
        locked_by=locked_by,
        lock_timeout_seconds=lock_timeout_seconds,
    )
    if claimed_run is None:
        return get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        )

    enrichment_run = enrich_article(
        database_url=database_url,
        article_id=claimed_run.article_id,
        translator=translator,
        summarizer_tagger=summarizer_tagger,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        force_reenrich=bool(
            existing_run is not None and existing_run.status == "manual_retry_requested"
        ),
    )
    if enrichment_run.status in ("succeeded", "skipped_advertisement"):
        return succeed_article_processing_run(
            database_url=database_url,
            article_key=article_key,
            last_success_input_hash=enrichment_run.input_hash,
        )

    return fail_article_processing_run(
        database_url=database_url,
        article_key=article_key,
        failed_step="enrich",
        error_message=enrichment_run.error_message or f"article enrichment ended with status {enrichment_run.status}",
        automatic_failure_limit=automatic_failure_limit,
    )


def process_document(
    *,
    database_url: str,
    document_key: str,
    locked_by: str,
    parse_persist_document=None,
    output_root: Path | str | None = None,
    mineru_client=None,
    continuation_matcher=None,
    parser_name: str = "",
    parser_version: str = "",
    continuation_matcher_name: str = "",
    continuation_matcher_version: str = "",
    enrich_document=None,
    translator=None,
    summarizer_tagger=None,
    provider_name: str = "",
    model_name: str = "",
    prompt_version: str = "",
    step_retry_limit: int = 2,
    lock_timeout_seconds: int = 600,
    scheduler_run_id: str | None = None,
    log_event=None,
) -> DocumentProcessingRun:
    create_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )
    claimed_run = claim_document_processing_run(
        database_url=database_url,
        document_key=document_key,
        locked_by=locked_by,
        lock_timeout_seconds=lock_timeout_seconds,
        scheduler_run_id=scheduler_run_id,
    )
    if claimed_run is None:
        return get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        )
    _log_event(
        log_event,
        event="document.claimed",
        details={
            "document_key": document_key,
            "scheduler_run_id": scheduler_run_id,
            "locked_by": locked_by,
        },
    )

    if parse_persist_document is None:
        parse_persist_document = _build_parse_persist_callback(
            database_url=database_url,
            output_root=output_root,
            mineru_client=mineru_client,
            continuation_matcher=continuation_matcher,
            parser_name=parser_name,
            parser_version=parser_version,
            continuation_matcher_name=continuation_matcher_name,
            continuation_matcher_version=continuation_matcher_version,
        )

    parse_error = _run_step_with_retry(
        callback=parse_persist_document,
        document_key=document_key,
        step_name="parse_persist",
        step_retry_limit=step_retry_limit,
        log_event=log_event,
    )
    if parse_error is not None:
        _log_event(
            log_event,
            event="document.step.finished",
            details={
                "document_key": document_key,
                "step": "parse_persist",
                "status": "failed",
            },
        )
        return fail_document_processing_run(
            database_url=database_url,
            document_key=document_key,
            failed_step="parse_persist",
            error_message=str(parse_error),
            log_event=log_event,
        )
    _log_event(
        log_event,
        event="document.step.finished",
        details={
            "document_key": document_key,
            "step": "parse_persist",
            "status": "succeeded",
        },
    )

    _update_document_processing_current_step(
        database_url=database_url,
        document_key=document_key,
        current_step="enrich",
    )
    if enrich_document is None:
        enrich_document = _build_article_processing_enqueue_callback(
            database_url=database_url,
        )
    enrich_error = _run_step_with_retry(
        callback=enrich_document,
        document_key=document_key,
        step_name="enrich",
        step_retry_limit=step_retry_limit,
        log_event=log_event,
    )
    if enrich_error is not None:
        _log_event(
            log_event,
            event="document.step.finished",
            details={
                "document_key": document_key,
                "step": "enrich",
                "status": "failed",
            },
        )
        return fail_document_processing_run(
            database_url=database_url,
            document_key=document_key,
            failed_step="enrich",
            error_message=str(enrich_error),
            log_event=log_event,
        )
    _log_event(
        log_event,
        event="document.step.finished",
        details={
            "document_key": document_key,
            "step": "enrich",
            "status": "succeeded",
        },
    )

    return succeed_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )


def _run_step_with_retry(
    *,
    callback,
    document_key: str,
    step_name: str,
    step_retry_limit: int,
    log_event=None,
):
    last_error = None
    _log_event(
        log_event,
        event="document.step.started",
        details={
            "document_key": document_key,
            "step": step_name,
        },
    )
    for attempt in range(step_retry_limit + 1):
        try:
            callback(document_key=document_key)
            return None
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < step_retry_limit:
                _log_event(
                    log_event,
                    event="document.step.retry_scheduled",
                    details={
                        "document_key": document_key,
                        "step": step_name,
                        "attempt": attempt + 1,
                        "error_message": str(exc),
                    },
                )
    return last_error


def _update_document_processing_current_step(
    *,
    database_url: str,
    document_key: str,
    current_step: str,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE document_processing_runs
            SET
                current_step = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE document_key = ?
            """,
            (
                current_step,
                document_key,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def enrich_document_articles(
    *,
    database_url: str,
    document_key: str,
    translator,
    summarizer_tagger,
    provider_name: str,
    model_name: str,
    prompt_version: str,
):
    articles = list_latest_document_articles(
        database_url=database_url,
        document_key=document_key,
    )
    if not articles:
        raise LookupError(f"No latest document articles found for: {document_key}")

    runs = []
    failed_runs = []
    for article in articles:
        run = enrich_article(
            database_url=database_url,
            article_id=article.article_id,
            translator=translator,
            summarizer_tagger=summarizer_tagger,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
        )
        runs.append(run)
        if run.status != "succeeded":
            failed_runs.append((article.article_id, run.status))

    if failed_runs:
        failure_details = ", ".join(
            f"{article_id}: {status}" for article_id, status in failed_runs
        )
        raise RuntimeError(
            f"Article enrichment did not succeed for {failure_details}"
        )
    return runs


def enqueue_document_article_processing_runs(
    *,
    database_url: str,
    document_key: str,
) -> list[ArticleProcessingRun]:
    articles = list_latest_document_articles(
        database_url=database_url,
        document_key=document_key,
    )
    if not articles:
        raise LookupError(f"No latest document articles found for: {document_key}")

    processing_runs = [
        create_article_processing_run(
            database_url=database_url,
            article_id=article.article_id,
        )
        for article in articles
    ]
    return [
        run
        for run in processing_runs
        if run.status in ("pending", "failed_retryable", "manual_retry_requested")
    ]


def _build_article_processing_enqueue_callback(
    *,
    database_url: str,
):
    def _callback(*, document_key: str) -> None:
        enqueue_document_article_processing_runs(
            database_url=database_url,
            document_key=document_key,
        )

    return _callback


def _build_parse_persist_callback(
    *,
    database_url: str,
    output_root: Path | str | None,
    mineru_client,
    continuation_matcher,
    parser_name: str,
    parser_version: str,
    continuation_matcher_name: str,
    continuation_matcher_version: str,
):
    if output_root is None:
        raise ValueError("output_root is required when parse_persist_document is not provided")
    if mineru_client is None:
        raise ValueError("mineru_client is required when parse_persist_document is not provided")

    def _callback(*, document_key: str) -> None:
        persist_document_articles(
            database_url=database_url,
            document_key=document_key,
            output_root=Path(output_root),
            mineru_client=mineru_client,
            continuation_matcher=continuation_matcher,
            parser_name=parser_name,
            parser_version=parser_version,
            continuation_matcher_name=continuation_matcher_name,
            continuation_matcher_version=continuation_matcher_version,
        )

    return _callback


def recover_stale_document_runs(
    *,
    database_url: str,
    running_timeout_seconds: int,
    automatic_failure_limit: int = 2,
    log_event=None,
) -> list[DocumentProcessingRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT document_key
            FROM document_processing_runs
            WHERE status = 'running'
              AND last_attempt_started_at IS NOT NULL
              AND last_attempt_started_at <= datetime(
                    CURRENT_TIMESTAMP,
                    '-' || ? || ' seconds'
              )
            ORDER BY last_attempt_started_at ASC, rowid ASC
            """,
            (running_timeout_seconds,),
        ).fetchall()
    finally:
        connection.close()

    recovered_runs = []
    for row in rows:
        stale_run = get_document_processing_run(
            database_url=database_url,
            document_key=row[0],
        )
        recovered_runs.append(
            fail_document_processing_run(
                database_url=database_url,
                document_key=stale_run.document_key,
                failed_step=stale_run.current_step,
                error_message="stale running timeout during automatic recovery",
                automatic_failure_limit=automatic_failure_limit,
                log_event=_noop_log_event,
            )
        )
        _log_event(
            log_event,
            event="document.recovered_stale",
            details={
                "document_key": stale_run.document_key,
                "failed_step": stale_run.current_step,
            },
        )
    return recovered_runs


def recover_stale_article_runs(
    *,
    database_url: str,
    running_timeout_seconds: int,
    automatic_failure_limit: int = 2,
) -> list[ArticleProcessingRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT article_key
            FROM article_processing_runs
            WHERE status = 'running'
              AND last_attempt_started_at IS NOT NULL
              AND last_attempt_started_at <= datetime(
                    CURRENT_TIMESTAMP,
                    '-' || ? || ' seconds'
              )
            ORDER BY last_attempt_started_at ASC, rowid ASC
            """,
            (running_timeout_seconds,),
        ).fetchall()
    finally:
        connection.close()

    recovered_runs = []
    for row in rows:
        recovered_runs.append(
            fail_article_processing_run(
                database_url=database_url,
                article_key=row[0],
                failed_step="enrich",
                error_message="stale running timeout during automatic recovery",
                automatic_failure_limit=automatic_failure_limit,
            )
        )
    return recovered_runs


def run_scheduler_tick(
    *,
    database_url: str,
    trigger_type: str,
    import_documents,
    process_one_document,
    document_limit: int,
    process_one_article=None,
    article_limit: int = 0,
    article_batch_size: int | None = None,
    locked_by_prefix: str = "scheduler-worker",
    article_locked_by_prefix: str = "article-worker",
    log_event=None,
) -> "ProcessingTickResult":
    _log_event(log_event, event="scheduler.tick.started", details={"trigger_type": trigger_type})
    _log_event(log_event, event="scheduler.import.started", details={"trigger_type": trigger_type})
    import_result = import_documents()
    import_run_id = getattr(import_result, "run_id", None)
    _log_event(log_event, event="scheduler.import.finished", details={"trigger_type": trigger_type, "import_run_id": import_run_id})
    finalized_run = run_processing_tick(
        database_url=database_url,
        trigger_type=trigger_type,
        process_one_document=process_one_document,
        document_limit=document_limit,
        process_one_article=process_one_article,
        article_limit=article_limit,
        article_batch_size=article_batch_size,
        import_run_id=import_run_id,
        locked_by_prefix=locked_by_prefix,
        article_locked_by_prefix=article_locked_by_prefix,
        log_event=log_event,
    )
    _log_event(
        log_event,
        event="scheduler.tick.finished",
        details={
            "scheduler_run_id": finalized_run.scheduler_run_id,
            "did_work": finalized_run.did_work,
            "selected_document_count": finalized_run.selected_document_count,
            "completed_document_count": finalized_run.completed_document_count,
            "failed_document_count": finalized_run.failed_document_count,
        },
    )
    return finalized_run


def run_document_processing_drain(
    *,
    database_url: str,
    process_one_document,
    document_limit: int,
    scheduler_run_id: str,
    locked_by_prefix: str = "scheduler-worker",
) -> DrainResult:
    if document_limit <= 0:
        return DrainResult(
            did_work=False,
            selected_count=0,
            completed_count=0,
            failed_count=0,
        )

    selected_count = 0
    completed_count = 0
    failed_count = 0
    error_messages: list[str] = []
    worker_counter = 0

    with ThreadPoolExecutor(max_workers=document_limit) as executor:
        in_flight = {}

        while True:
            while len(in_flight) < document_limit:
                eligible_runs = list_eligible_document_processing_runs(
                    database_url=database_url,
                    limit=document_limit,
                )
                if not eligible_runs:
                    break

                in_flight_document_keys = set(in_flight.values())
                next_run = next(
                    (
                        eligible_run
                        for eligible_run in eligible_runs
                        if eligible_run.document_key not in in_flight_document_keys
                    ),
                    None,
                )
                if next_run is None:
                    break

                worker_counter += 1
                locked_by = f"{locked_by_prefix}-{worker_counter}"
                future = executor.submit(
                    process_one_document,
                    document_key=next_run.document_key,
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                )
                in_flight[future] = next_run.document_key
                selected_count += 1

            if not in_flight:
                break

            completed_futures, _pending_futures = wait(
                set(in_flight),
                return_when=FIRST_COMPLETED,
            )
            for future in completed_futures:
                in_flight.pop(future, None)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_count += 1
                    error_messages.append(str(exc))
                    continue

                if getattr(result, "status", "") == "succeeded":
                    completed_count += 1
                else:
                    failed_count += 1

    return DrainResult(
        did_work=selected_count > 0,
        selected_count=selected_count,
        completed_count=completed_count,
        failed_count=failed_count,
        error_messages=tuple(error_messages),
    )


def run_processing_tick(
    *,
    database_url: str,
    trigger_type: str,
    process_one_document,
    document_limit: int,
    process_one_article=None,
    article_limit: int = 0,
    article_batch_size: int | None = None,
    import_run_id: str | None = None,
    locked_by_prefix: str = "scheduler-worker",
    article_locked_by_prefix: str = "article-worker",
    log_event=None,
) -> "ProcessingTickResult":
    if article_batch_size is None:
        article_batch_size = article_limit

    eligible_runs = list_eligible_document_processing_runs(
        database_url=database_url,
        limit=document_limit,
    )
    eligible_article_runs = (
        list_eligible_article_processing_runs(
            database_url=database_url,
            limit=article_batch_size,
        )
        if process_one_article is not None and article_batch_size > 0
        else []
    )

    if not eligible_runs and not eligible_article_runs:
        _log_event(
            log_event,
            event="scheduler.processing.idle",
            details={"trigger_type": trigger_type},
        )
        return ProcessingTickResult(
            scheduler_run_id=None,
            did_work=False,
            selected_document_count=0,
            completed_document_count=0,
            failed_document_count=0,
        )

    scheduler_run = create_scheduler_run(
        database_url=database_url,
        trigger_type=trigger_type,
    )
    _log_event(
        log_event,
        event="scheduler.processing.started",
        details={
            "scheduler_run_id": scheduler_run.scheduler_run_id,
            "trigger_type": trigger_type,
        },
    )

    completed_document_count = 0
    failed_document_count = 0
    error_messages: list[str] = []
    if eligible_runs:
        max_workers = max(1, len(eligible_runs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_document_key = {
                executor.submit(
                    process_one_document,
                    document_key=eligible_run.document_key,
                    scheduler_run_id=scheduler_run.scheduler_run_id,
                    locked_by=f"{locked_by_prefix}-{index}",
                ): eligible_run.document_key
                for index, eligible_run in enumerate(eligible_runs, start=1)
            }
            for future in as_completed(future_to_document_key):
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_document_count += 1
                    error_messages.append(str(exc))
                    continue

                if getattr(result, "status", "") == "succeeded":
                    completed_document_count += 1
                else:
                    failed_document_count += 1

    if eligible_article_runs:
        max_article_workers = max(1, min(article_limit, len(eligible_article_runs)))
        with ThreadPoolExecutor(max_workers=max_article_workers) as executor:
            future_to_article_key = {
                executor.submit(
                    process_one_article,
                    article_key=eligible_run.article_key,
                    locked_by=f"{article_locked_by_prefix}-{index}",
                ): eligible_run.article_key
                for index, eligible_run in enumerate(eligible_article_runs, start=1)
            }
            for future in as_completed(future_to_article_key):
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_document_count += 1
                    error_messages.append(str(exc))
                    continue

                if getattr(result, "status", "") == "succeeded":
                    completed_document_count += 1
                else:
                    failed_document_count += 1

    final_status = "succeeded"
    if failed_document_count and completed_document_count:
        final_status = "partial"
    elif failed_document_count:
        final_status = "failed"

    selected_document_count = len(eligible_runs) + len(eligible_article_runs)
    finalize_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
        status=final_status,
        import_run_id=import_run_id,
        selected_document_count=selected_document_count,
        completed_document_count=completed_document_count,
        failed_document_count=failed_document_count,
        error_message="; ".join(error_messages) if error_messages else None,
    )
    finalized_run = get_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
    )
    _log_event(
        log_event,
        event="scheduler.processing.finished",
        details={
            "scheduler_run_id": finalized_run.scheduler_run_id,
            "status": finalized_run.status,
            "selected_document_count": finalized_run.selected_document_count,
            "completed_document_count": finalized_run.completed_document_count,
            "failed_document_count": finalized_run.failed_document_count,
        },
    )
    return ProcessingTickResult(
        scheduler_run_id=finalized_run.scheduler_run_id,
        did_work=True,
        selected_document_count=finalized_run.selected_document_count,
        completed_document_count=finalized_run.completed_document_count,
        failed_document_count=finalized_run.failed_document_count,
    )


def _row_to_scheduler_run(row) -> SchedulerRun:
    return SchedulerRun(
        scheduler_run_id=row[0],
        trigger_type=row[1],
        status=row[2],
        started_at=row[3],
        finished_at=row[4],
        import_run_id=row[5],
        selected_document_count=row[6],
        completed_document_count=row[7],
        failed_document_count=row[8],
        error_message=row[9],
    )


def _row_to_document_processing_run(row) -> DocumentProcessingRun:
    return DocumentProcessingRun(
        processing_run_id=row[0],
        scheduler_run_id=row[1],
        document_key=row[2],
        status=row[3],
        current_step=row[4],
        automatic_failure_count=row[5],
        last_failure_step=row[6],
        last_error_message=row[7],
        last_attempt_started_at=row[8],
        last_attempt_finished_at=row[9],
        locked_by=row[10],
        lock_expires_at=row[11],
        created_at=row[12],
        updated_at=row[13],
    )


def _row_to_article_processing_run(row) -> ArticleProcessingRun:
    return ArticleProcessingRun(
        article_processing_run_id=row[0],
        article_key=row[1],
        article_id=row[2],
        status=row[3],
        current_step=row[4],
        automatic_failure_count=row[5],
        last_error_message=row[6],
        last_success_input_hash=row[7],
        last_attempt_started_at=row[8],
        last_attempt_finished_at=row[9],
        locked_by=row[10],
        lock_expires_at=row[11],
        created_at=row[12],
        updated_at=row[13],
    )


def _get_article_key_for_article_id(*, database_url: str, article_id: str) -> str:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
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

    if row is None:
        raise LookupError(f"Final article not found for article processing: {article_id}")
    return row[0]


def _log_event(log_event, *, event: str, details: dict[str, object]) -> None:
    if log_event is not None:
        log_event(event=event, details=details)
        return
    print(
        format_log_event(
            level="INFO",
            event=event,
            service="worker",
            details=details,
        ),
        flush=True,
    )


def _noop_log_event(*, event: str, details: dict[str, object]) -> None:
    return None
