from dataclasses import dataclass
import sqlite3
import uuid

from newspaper_translator.database import sqlite_path_from_database_url


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
        DocumentProcessingRun(
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
        for row in rows
    ]
