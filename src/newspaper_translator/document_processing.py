from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
import uuid

from newspaper_translator.article_enrichment import build_article_input_hash, enrich_article
from newspaper_translator.article_pipeline import (
    StoredDocument,
    _get_document,
    persist_bloomberg_edition_articles,
    persist_document_articles,
    persist_economist_edition_articles,
)
from newspaper_translator.bloomberg_edition import detect_bloomberg_edition
from newspaper_translator.economist_edition import (
    ECONOMIST_EDITION_PARSER_VERSION,
    detect_calibre_economist_edition,
)
from newspaper_translator.article_store import get_final_article, list_latest_document_articles
from newspaper_translator.logging_utils import format_log_event
from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.mineru import MineruRateLimitError


ARTICLE_STAGE_AWAIT_AD_JUDGMENT = "await_ad_judgment"
ARTICLE_STAGE_AWAIT_TRANSLATION = "await_translation"
ARTICLE_STAGE_AWAIT_SUMMARY = "await_summary"
ARTICLE_STAGE_AWAIT_TAGGING = "await_tagging"
ARTICLE_STAGE_COMPLETED = "completed"
ARTICLE_STAGE_ADVERTISEMENT = "classified_as_advertisement"

_ENRICH_STEP_TO_ARTICLE_STAGE = {
    "ad_judgment": ARTICLE_STAGE_AWAIT_AD_JUDGMENT,
    "translation": ARTICLE_STAGE_AWAIT_TRANSLATION,
    "summary": ARTICLE_STAGE_AWAIT_SUMMARY,
    "tagging": ARTICLE_STAGE_AWAIT_TAGGING,
}


def advance_article_processing_step(
    *,
    database_url: str,
    article_key: str,
    current_step: str,
) -> None:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            connection.execute(
                """
                UPDATE article_processing_runs
                SET current_step = ?, updated_at = CURRENT_TIMESTAMP
                WHERE article_key = ?
                """,
                (current_step, article_key),
            )
            connection.commit()
        finally:
            connection.close()

    _run_with_database_retries(callback)


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


@dataclass(frozen=True)
class BatchRetrySummary:
    matched_count: int
    updated_count: int
    skipped_count: int


DATABASE_RETRY_DELAYS_SECONDS = (0.2, 0.5, 1.0)


def _is_retryable_sqlite_error(exc) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, sqlite3.OperationalError)
        and any(
            lock_message in message
            for lock_message in (
                "database is locked",
                "database table is locked",
                "database schema is locked",
            )
        )
    )


def _run_with_database_retries(callback, *, sleep_fn=time.sleep):
    for retry_delay_seconds in DATABASE_RETRY_DELAYS_SECONDS:
        try:
            return callback()
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable_sqlite_error(exc):
                raise
            sleep_fn(retry_delay_seconds)
    return callback()


def create_scheduler_run(*, database_url: str, trigger_type: str) -> SchedulerRun:
    scheduler_run_id = str(uuid.uuid4())

    def callback():
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

    _run_with_database_retries(callback)
    return _run_with_database_retries(
        lambda: get_scheduler_run(
            database_url=database_url,
            scheduler_run_id=scheduler_run_id,
        ),
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
    def callback():
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

    _run_with_database_retries(callback)


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
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            return connection.execute(
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

    row = _run_with_database_retries(callback)

    if row is None:
        return None
    return _row_to_scheduler_run(row)


def create_document_processing_run(
    *,
    database_url: str,
    document_key: str,
) -> DocumentProcessingRun:
    processing_run_id = str(uuid.uuid4())

    def callback():
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
            return cursor.rowcount
        finally:
            connection.close()

    _run_with_database_retries(callback)
    return _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
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

    def callback():
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
                        "await_ad_judgment",
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
                            current_step = 'await_ad_judgment',
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

    _run_with_database_retries(callback)
    return _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
    )


def claim_document_processing_run(
    *,
    database_url: str,
    document_key: str,
    locked_by: str,
    lock_timeout_seconds: int,
    scheduler_run_id: str | None = None,
) -> DocumentProcessingRun | None:
    def callback():
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
            return cursor.rowcount
        finally:
            connection.close()

    rowcount = _run_with_database_retries(callback)

    if rowcount == 0:
        return None
    return _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
    )


def claim_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    locked_by: str,
    lock_timeout_seconds: int,
) -> ArticleProcessingRun | None:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            cursor = connection.execute(
                """
                UPDATE article_processing_runs
                SET
                    status = CASE
                        WHEN status = 'manual_retry_requested' THEN 'running_manual_retry'
                        ELSE 'running'
                    END,
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
            return cursor.rowcount
        finally:
            connection.close()

    rowcount = _run_with_database_retries(callback)

    if rowcount == 0:
        return None
    return _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
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
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            return connection.execute(
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

    rows = _run_with_database_retries(callback)

    return [
        _row_to_document_processing_run(row)
        for row in rows
    ]


def list_eligible_article_processing_runs(
    *,
    database_url: str,
    limit: int,
) -> list[ArticleProcessingRun]:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            return connection.execute(
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

    rows = _run_with_database_retries(callback)

    return [_row_to_article_processing_run(row) for row in rows]


def list_document_processing_runs(
    *,
    database_url: str,
    limit: int,
    status: str | None = None,
    min_failure_count: int | None = None,
) -> list[DocumentProcessingRun]:
    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if min_failure_count is not None:
        clauses.append("automatic_failure_count >= ?")
        params.append(min_failure_count)
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

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
            """
            + where_sql
            + """
            ORDER BY updated_at DESC, created_at DESC, rowid DESC
            LIMIT ?
            """,
            tuple([*params, limit]),
        ).fetchall()
    finally:
        connection.close()

    return [_row_to_document_processing_run(row) for row in rows]


def get_document_processing_max_failure_count(*, database_url: str) -> int:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(automatic_failure_count), 0)
            FROM document_processing_runs
            """
        ).fetchone()
    finally:
        connection.close()
    return int(row[0])


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
    stored_run = _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
    )
    new_failure_count = stored_run.automatic_failure_count + 1
    new_status = (
        "failed_terminal"
        if new_failure_count >= automatic_failure_limit
        else "failed_retryable"
    )

    def callback():
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

    _run_with_database_retries(callback)

    updated_run = _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
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


def mark_document_rate_limited(
    *,
    database_url: str,
    document_key: str,
    failed_step: str,
    error_message: str,
    log_event=None,
) -> DocumentProcessingRun:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            connection.execute(
                """
                UPDATE document_processing_runs
                SET
                    status = 'failed_retryable',
                    current_step = ?,
                    last_failure_step = ?,
                    last_error_message = ?,
                    last_attempt_finished_at = CURRENT_TIMESTAMP,
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE document_key = ?
                """,
                (failed_step, failed_step, error_message, document_key),
            )
            connection.commit()
        finally:
            connection.close()

    _run_with_database_retries(callback)
    updated_run = _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url, document_key=document_key,
        ),
    )
    _log_event(
        log_event,
        event="document.rate_limited",
        details={
            "document_key": document_key,
            "failed_step": failed_step,
            "status": updated_run.status,
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
    stored_run = _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
    )
    new_failure_count = stored_run.automatic_failure_count + 1
    new_status = (
        "failed_terminal"
        if new_failure_count >= automatic_failure_limit
        else "failed_retryable"
    )
    def callback():
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

    _run_with_database_retries(callback)
    return _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
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


def retry_article_processing_runs(
    *,
    database_url: str,
    article_keys: list[str] | None = None,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
) -> BatchRetrySummary:
    has_filter_scope = any(
        value is not None
        for value in (
            status,
            source,
            publication_date_from,
            publication_date_to,
            step,
            error_message,
        )
    )
    if has_filter_scope and article_keys is not None:
        raise ValueError("article_keys cannot be combined with filter arguments")
    matched_rows = _list_article_processing_runs_for_retry(
        database_url=database_url,
        article_keys=None if has_filter_scope else article_keys,
        status=status,
        source=source,
        publication_date_from=publication_date_from,
        publication_date_to=publication_date_to,
        step=step,
        error_message=error_message,
    )
    matched_count = len(matched_rows)
    retryable_article_keys = [
        article_key
        for article_key, run_status in matched_rows
        if run_status in ("failed_retryable", "failed_terminal")
    ]
    updated_count = 0
    if retryable_article_keys:
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            placeholders = ", ".join("?" for _ in retryable_article_keys)
            cursor = connection.execute(
                f"""
                UPDATE article_processing_runs
                SET
                    status = 'manual_retry_requested',
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE article_key IN ({placeholders})
                  AND status IN ('failed_retryable', 'failed_terminal')
                """,
                tuple(retryable_article_keys),
            )
            updated_count = max(cursor.rowcount, 0)
            connection.commit()
        finally:
            connection.close()

    return BatchRetrySummary(
        matched_count=matched_count,
        updated_count=updated_count,
        skipped_count=matched_count - updated_count,
    )


def _list_article_processing_runs_for_retry(
    *,
    database_url: str,
    article_keys: list[str] | None = None,
    status: str | None = None,
    source: str | None = None,
    publication_date_from: str | None = None,
    publication_date_to: str | None = None,
    step: str | None = None,
    error_message: str | None = None,
) -> list[tuple[str, str]]:
    clauses: list[str] = []
    params: list[object] = []
    if article_keys is not None:
        if not article_keys:
            return []
        placeholders = ", ".join("?" for _ in article_keys)
        clauses.append(f"r.article_key IN ({placeholders})")
        params.extend(article_keys)
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

    query = """
    SELECT r.article_key, r.status
    FROM article_processing_runs r
    JOIN final_articles a
        ON a.article_id = r.article_id
    JOIN documents d
        ON d.document_key = a.document_key
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY r.updated_at DESC, r.created_at DESC, r.rowid DESC"

    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(query, tuple(params)).fetchall()
    finally:
        connection.close()
    return [(row[0], row[1]) for row in rows]


def succeed_document_processing_run(
    *,
    database_url: str,
    document_key: str,
) -> DocumentProcessingRun:
    def callback():
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

    _run_with_database_retries(callback)
    return _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
    )


def succeed_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    last_success_input_hash: str,
    current_step: str = "completed",
) -> ArticleProcessingRun:
    def callback():
        connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
        try:
            connection.execute(
                """
                UPDATE article_processing_runs
                SET
                    status = 'succeeded',
                    current_step = ?,
                    last_success_input_hash = ?,
                    last_attempt_finished_at = CURRENT_TIMESTAMP,
                    locked_by = NULL,
                    lock_expires_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE article_key = ?
                """,
                (
                    current_step,
                    last_success_input_hash,
                    article_key,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    _run_with_database_retries(callback)
    return _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
    )


def process_article_processing_run(
    *,
    database_url: str,
    article_key: str,
    locked_by: str,
    enricher,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    lock_timeout_seconds: int = 600,
    automatic_failure_limit: int = 2,
    preclaimed_run: ArticleProcessingRun | None = None,
) -> ArticleProcessingRun:
    existing_run = preclaimed_run
    if existing_run is None:
        try:
            existing_run = _run_with_database_retries(
                lambda: get_article_processing_run(
                    database_url=database_url,
                    article_key=article_key,
                ),
            )
        except LookupError:
            existing_run = None

    claimed_run, owns_run = _resolve_article_processing_run_for_execution(
        database_url=database_url,
        article_key=article_key,
        locked_by=locked_by,
        lock_timeout_seconds=lock_timeout_seconds,
        preclaimed_run=preclaimed_run,
    )
    if not owns_run:
        return claimed_run

    last_stage = {"value": ARTICLE_STAGE_AWAIT_AD_JUDGMENT}

    def _on_step_advance(step_key: str) -> None:
        stage = _ENRICH_STEP_TO_ARTICLE_STAGE[step_key]
        last_stage["value"] = stage
        advance_article_processing_step(
            database_url=database_url,
            article_key=article_key,
            current_step=stage,
        )

    enrichment_run = enrich_article(
        database_url=database_url,
        article_id=claimed_run.article_id,
        enricher=enricher,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        on_step_advance=_on_step_advance,
        force_reenrich=bool(
            existing_run is not None
            and existing_run.status in ("manual_retry_requested", "running_manual_retry")
        ),
    )
    if enrichment_run.status == "skipped_advertisement":
        return succeed_article_processing_run(
            database_url=database_url,
            article_key=article_key,
            last_success_input_hash=enrichment_run.input_hash,
            current_step=ARTICLE_STAGE_ADVERTISEMENT,
        )
    if enrichment_run.status == "succeeded":
        return succeed_article_processing_run(
            database_url=database_url,
            article_key=article_key,
            last_success_input_hash=enrichment_run.input_hash,
            current_step=ARTICLE_STAGE_COMPLETED,
        )

    return fail_article_processing_run(
        database_url=database_url,
        article_key=article_key,
        failed_step=last_stage["value"],
        error_message=enrichment_run.error_message
        or f"article enrichment ended with status {enrichment_run.status}",
        automatic_failure_limit=automatic_failure_limit,
    )


def _resolve_article_processing_run_for_execution(
    *,
    database_url: str,
    article_key: str,
    locked_by: str,
    lock_timeout_seconds: int,
    preclaimed_run: ArticleProcessingRun | None = None,
) -> tuple[ArticleProcessingRun, bool]:
    current_run = _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
    )

    if preclaimed_run is not None:
        if preclaimed_run.article_key != article_key:
            raise ValueError("preclaimed run article_key does not match request")
        if current_run.article_processing_run_id != preclaimed_run.article_processing_run_id:
            return current_run, False

    if _article_processing_run_is_owned_by(
        current_run,
        locked_by=locked_by,
    ):
        return current_run, True

    claimed_run = claim_article_processing_run(
        database_url=database_url,
        article_key=article_key,
        locked_by=locked_by,
        lock_timeout_seconds=lock_timeout_seconds,
    )
    if claimed_run is not None:
        return claimed_run, True

    return _run_with_database_retries(
        lambda: get_article_processing_run(
            database_url=database_url,
            article_key=article_key,
        ),
    ), False


def _article_processing_run_is_owned_by(
    run: ArticleProcessingRun,
    *,
    locked_by: str,
) -> bool:
    return (
        run.status in ("running", "running_manual_retry")
        and run.locked_by == locked_by
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
    provider_name: str = "",
    model_name: str = "",
    prompt_version: str = "",
    step_retry_limit: int = 2,
    lock_timeout_seconds: int = 600,
    scheduler_run_id: str | None = None,
    preclaimed_run: DocumentProcessingRun | None = None,
    log_event=None,
) -> DocumentProcessingRun:
    claimed_run, owns_run = _resolve_document_processing_run_for_execution(
        database_url=database_url,
        document_key=document_key,
        locked_by=locked_by,
        lock_timeout_seconds=lock_timeout_seconds,
        scheduler_run_id=scheduler_run_id,
        preclaimed_run=preclaimed_run,
    )
    if not owns_run:
        return claimed_run
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
        if isinstance(parse_error, MineruRateLimitError):
            return mark_document_rate_limited(
                database_url=database_url,
                document_key=document_key,
                failed_step="parse_persist",
                error_message=str(parse_error),
                log_event=log_event,
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


def _resolve_document_processing_run_for_execution(
    *,
    database_url: str,
    document_key: str,
    locked_by: str,
    lock_timeout_seconds: int,
    scheduler_run_id: str | None,
    preclaimed_run: DocumentProcessingRun | None = None,
) -> tuple[DocumentProcessingRun, bool]:
    create_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )

    if preclaimed_run is not None:
        _validate_preclaimed_document_processing_run(
            document_key=document_key,
            locked_by=locked_by,
            scheduler_run_id=scheduler_run_id,
            preclaimed_run=preclaimed_run,
        )
        current_run = _run_with_database_retries(
            lambda: get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            ),
        )
        return current_run, (
            current_run.processing_run_id == preclaimed_run.processing_run_id
            and _document_processing_run_is_owned_by(
                current_run,
                locked_by=locked_by,
                scheduler_run_id=scheduler_run_id,
            )
        )

    current_run = _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
    )
    if _document_processing_run_is_owned_by(
        current_run,
        locked_by=locked_by,
        scheduler_run_id=scheduler_run_id,
    ):
        return current_run, True

    claimed_run = claim_document_processing_run(
        database_url=database_url,
        document_key=document_key,
        locked_by=locked_by,
        lock_timeout_seconds=lock_timeout_seconds,
        scheduler_run_id=scheduler_run_id,
    )
    if claimed_run is not None:
        return claimed_run, True

    return _run_with_database_retries(
        lambda: get_document_processing_run(
            database_url=database_url,
            document_key=document_key,
        ),
    ), False


def _validate_preclaimed_document_processing_run(
    *,
    document_key: str,
    locked_by: str,
    scheduler_run_id: str | None,
    preclaimed_run: DocumentProcessingRun,
) -> None:
    if preclaimed_run.document_key != document_key:
        raise ValueError("preclaimed run document_key does not match request")
    if not _document_processing_run_is_owned_by(
        preclaimed_run,
        locked_by=locked_by,
        scheduler_run_id=scheduler_run_id,
    ):
        raise ValueError("preclaimed run ownership does not match request")


def _document_processing_run_is_owned_by(
    run: DocumentProcessingRun,
    *,
    locked_by: str,
    scheduler_run_id: str | None,
) -> bool:
    return (
        run.status == "running"
        and run.locked_by == locked_by
        and run.scheduler_run_id == scheduler_run_id
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
        except MineruRateLimitError as exc:
            return exc
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
    def callback():
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

    _run_with_database_retries(callback)


def enrich_document_articles(
    *,
    database_url: str,
    document_key: str,
    enricher,
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
            enricher=enricher,
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
        document = _get_document(database_url=database_url, document_key=document_key)
        if detect_calibre_economist_edition(Path(document.raw_path)):
            persist_economist_edition_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=Path(output_root),
                parser_name="economist-edition",
                parser_version=ECONOMIST_EDITION_PARSER_VERSION,
            )
            return
        if detect_bloomberg_edition(Path(document.raw_path)):
            persist_bloomberg_edition_articles(
                database_url=database_url,
                document_key=document_key,
                output_root=Path(output_root),
            )
            return
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
            WHERE status IN ('running', 'running_manual_retry')
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
        stale_run = get_article_processing_run(
            database_url=database_url,
            article_key=row[0],
        )
        recovered_runs.append(
            fail_article_processing_run(
                database_url=database_url,
                article_key=stale_run.article_key,
                failed_step=stale_run.current_step,
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
    locked_by_prefix: str = "scheduler-worker",
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
        import_run_id=import_run_id,
        locked_by_prefix=locked_by_prefix,
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

                in_flight_document_keys = {
                    document_key
                    for document_key, _locked_by in in_flight.values()
                }
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
                claimed_run = claim_document_processing_run(
                    database_url=database_url,
                    document_key=next_run.document_key,
                    locked_by=locked_by,
                    lock_timeout_seconds=600,
                    scheduler_run_id=scheduler_run_id,
                )
                if claimed_run is None:
                    continue
                future = executor.submit(
                    process_one_document,
                    document_key=claimed_run.document_key,
                    scheduler_run_id=scheduler_run_id,
                    locked_by=locked_by,
                )
                in_flight[future] = (claimed_run.document_key, locked_by)
                selected_count += 1

            if not in_flight:
                break

            completed_futures, _pending_futures = wait(
                set(in_flight),
                return_when=FIRST_COMPLETED,
            )
            for future in completed_futures:
                future_metadata = in_flight.pop(future, None)
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


def run_article_processing_drain(
    *,
    database_url: str,
    process_one_article,
    article_limit: int,
    locked_by_prefix: str = "article-worker",
) -> DrainResult:
    if article_limit <= 0:
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

    with ThreadPoolExecutor(max_workers=article_limit) as executor:
        in_flight = {}

        while True:
            while len(in_flight) < article_limit:
                eligible_runs = list_eligible_article_processing_runs(
                    database_url=database_url,
                    limit=article_limit,
                )
                if not eligible_runs:
                    break

                in_flight_article_keys = {
                    article_key
                    for article_key, _locked_by in in_flight.values()
                }
                next_run = next(
                    (
                        eligible_run
                        for eligible_run in eligible_runs
                        if eligible_run.article_key not in in_flight_article_keys
                    ),
                    None,
                )
                if next_run is None:
                    break

                worker_counter += 1
                locked_by = f"{locked_by_prefix}-{worker_counter}"
                claimed_run = claim_article_processing_run(
                    database_url=database_url,
                    article_key=next_run.article_key,
                    locked_by=locked_by,
                    lock_timeout_seconds=600,
                )
                if claimed_run is None:
                    continue

                future = executor.submit(
                    process_one_article,
                    article_key=claimed_run.article_key,
                    locked_by=locked_by,
                )
                in_flight[future] = (claimed_run.article_key, locked_by)
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
    import_run_id: str | None = None,
    locked_by_prefix: str = "scheduler-worker",
    log_event=None,
) -> "ProcessingTickResult":
    has_document_work = bool(
        list_eligible_document_processing_runs(
            database_url=database_url,
            limit=1,
        )
    ) if document_limit > 0 else False

    if not has_document_work:
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

    def process_tick_document_callback(*, document_key: str, scheduler_run_id: str, locked_by: str):
        result = process_one_document(
            document_key=document_key,
            scheduler_run_id=scheduler_run_id,
            locked_by=locked_by,
        )
        if isinstance(result, DocumentProcessingRun):
            return result
        if getattr(result, "status", "") != "succeeded":
            return result

        current_run = _run_with_database_retries(
            lambda: get_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            ),
        )
        if _document_processing_run_is_owned_by(
            current_run,
            locked_by=locked_by,
            scheduler_run_id=scheduler_run_id,
        ):
            return succeed_document_processing_run(
                database_url=database_url,
                document_key=document_key,
            )
        return result

    document_drain_result = run_document_processing_drain(
        database_url=database_url,
        process_one_document=process_tick_document_callback,
        document_limit=document_limit,
        scheduler_run_id=scheduler_run.scheduler_run_id,
        locked_by_prefix=locked_by_prefix,
    )

    completed_document_count = document_drain_result.completed_count
    failed_document_count = document_drain_result.failed_count
    error_messages = list(document_drain_result.error_messages)

    final_status = "succeeded"
    if failed_document_count and completed_document_count:
        final_status = "partial"
    elif failed_document_count:
        final_status = "failed"

    selected_document_count = document_drain_result.selected_count
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
    finalized_run = _run_with_database_retries(
        lambda: get_scheduler_run(
            database_url=database_url,
            scheduler_run_id=scheduler_run.scheduler_run_id,
        ),
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
        did_work=document_drain_result.did_work,
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
