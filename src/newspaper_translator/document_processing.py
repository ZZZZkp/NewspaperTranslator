from dataclasses import dataclass
from pathlib import Path
import sqlite3
import uuid

from newspaper_translator.article_enrichment import enrich_article
from newspaper_translator.article_pipeline import persist_document_articles
from newspaper_translator.article_store import list_latest_document_articles
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


def fail_document_processing_run(
    *,
    database_url: str,
    document_key: str,
    failed_step: str,
    error_message: str,
    automatic_failure_limit: int = 2,
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

    return get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )


def request_manual_document_retry(
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

    return get_document_processing_run(
        database_url=database_url,
        document_key=document_key,
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
        step_retry_limit=step_retry_limit,
    )
    if parse_error is not None:
        return fail_document_processing_run(
            database_url=database_url,
            document_key=document_key,
            failed_step="parse_persist",
            error_message=str(parse_error),
        )

    _update_document_processing_current_step(
        database_url=database_url,
        document_key=document_key,
        current_step="enrich",
    )
    if enrich_document is None:
        enrich_document = _build_document_enrichment_callback(
            database_url=database_url,
            translator=translator,
            summarizer_tagger=summarizer_tagger,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
        )
    enrich_error = _run_step_with_retry(
        callback=enrich_document,
        document_key=document_key,
        step_retry_limit=step_retry_limit,
    )
    if enrich_error is not None:
        return fail_document_processing_run(
            database_url=database_url,
            document_key=document_key,
            failed_step="enrich",
            error_message=str(enrich_error),
        )

    return succeed_document_processing_run(
        database_url=database_url,
        document_key=document_key,
    )


def _run_step_with_retry(*, callback, document_key: str, step_retry_limit: int):
    last_error = None
    for _ in range(step_retry_limit + 1):
        try:
            callback(document_key=document_key)
            return None
        except Exception as exc:  # noqa: BLE001
            last_error = exc
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
            raise RuntimeError(
                f"Article enrichment did not succeed for {article.article_id}: {run.status}"
            )
    return runs


def _build_document_enrichment_callback(
    *,
    database_url: str,
    translator,
    summarizer_tagger,
    provider_name: str,
    model_name: str,
    prompt_version: str,
):
    def _callback(*, document_key: str) -> None:
        enrich_document_articles(
            database_url=database_url,
            document_key=document_key,
            translator=translator,
            summarizer_tagger=summarizer_tagger,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
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
) -> SchedulerRun:
    scheduler_run = create_scheduler_run(
        database_url=database_url,
        trigger_type=trigger_type,
    )

    import_result = import_documents()
    import_run_id = getattr(import_result, "run_id", None)
    eligible_runs = list_eligible_document_processing_runs(
        database_url=database_url,
        limit=document_limit,
    )

    completed_document_count = 0
    failed_document_count = 0
    error_messages: list[str] = []
    for index, eligible_run in enumerate(eligible_runs, start=1):
        try:
            result = process_one_document(
                document_key=eligible_run.document_key,
                scheduler_run_id=scheduler_run.scheduler_run_id,
                locked_by=f"{locked_by_prefix}-{index}",
            )
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

    finalize_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
        status=final_status,
        import_run_id=import_run_id,
        selected_document_count=len(eligible_runs),
        completed_document_count=completed_document_count,
        failed_document_count=failed_document_count,
        error_message="; ".join(error_messages) if error_messages else None,
    )
    return get_scheduler_run(
        database_url=database_url,
        scheduler_run_id=scheduler_run.scheduler_run_id,
    )
