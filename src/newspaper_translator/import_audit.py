from dataclasses import dataclass
import json
import sqlite3
import uuid

from newspaper_translator.database import sqlite_path_from_database_url


@dataclass(frozen=True)
class ImportRun:
    run_id: str
    source_name: str
    status: str
    query: str
    allowed_senders: list[str]
    max_results: int
    fetched_message_count: int
    imported_attachment_count: int
    created_document_count: int
    skipped_document_count: int
    failed_item_count: int
    skipped_item_count: int
    checkpoint_before: str | None
    checkpoint_after: str | None
    retry_performed: bool
    retry_run_id: str | None
    retried_message_count: int
    resolved_message_count: int
    failed_final_message_count: int
    started_at: str
    finished_at: str | None


@dataclass(frozen=True)
class ImportRunItem:
    id: int
    run_id: str
    item_type: str
    item_key: str
    message_id: str | None
    attachment_id: str | None
    link_url: str | None
    status: str
    detail_code: str
    detail_message: str
    document_key: str | None
    message_internal_date: str | None
    created_at: str


@dataclass(frozen=True)
class FailedMessage:
    message_id: str
    source_name: str
    message_internal_date: str
    retry_state: str
    retry_attempt_count: int
    last_run_id: str | None
    created_at: str
    updated_at: str


def create_import_run(
    *,
    database_url: str,
    source_name: str,
    query: str,
    allowed_senders: list[str],
    max_results: int,
    checkpoint_before: str | None = None,
) -> ImportRun:
    run_id = str(uuid.uuid4())
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO import_runs (
                run_id,
                source_name,
                status,
                query,
                allowed_senders_json,
                max_results,
                checkpoint_before
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source_name,
                "running",
                query,
                json.dumps(allowed_senders),
                max_results,
                checkpoint_before,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return get_import_run(database_url=database_url, run_id=run_id)


def record_import_run_item(
    *,
    database_url: str,
    run_id: str,
    item_type: str,
    item_key: str,
    message_id: str | None,
    attachment_id: str | None,
    link_url: str | None,
    status: str,
    detail_code: str,
    detail_message: str,
    document_key: str | None,
    message_internal_date: str | None = None,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO import_run_items (
                run_id,
                item_type,
                item_key,
                message_id,
                attachment_id,
                link_url,
                status,
                detail_code,
                detail_message,
                document_key,
                message_internal_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                item_type,
                item_key,
                message_id,
                attachment_id,
                link_url,
                status,
                detail_code,
                detail_message,
                document_key,
                message_internal_date,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def finalize_import_run(
    *,
    database_url: str,
    run_id: str,
    fetched_message_count: int,
    imported_attachment_count: int,
    created_document_count: int,
    skipped_document_count: int,
    checkpoint_after: str | None = None,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        failed_item_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM import_run_items
            WHERE run_id = ? AND status = 'failed'
            """,
            (run_id,),
        ).fetchone()[0]
        skipped_item_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM import_run_items
            WHERE run_id = ? AND status = 'skipped'
            """,
            (run_id,),
        ).fetchone()[0]
        status = "partial" if failed_item_count else "succeeded"

        connection.execute(
            """
            UPDATE import_runs
            SET
                status = ?,
                fetched_message_count = ?,
                imported_attachment_count = ?,
                created_document_count = ?,
                skipped_document_count = ?,
                failed_item_count = ?,
                skipped_item_count = ?,
                checkpoint_after = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
            """,
            (
                status,
                fetched_message_count,
                imported_attachment_count,
                created_document_count,
                skipped_document_count,
                failed_item_count,
                skipped_item_count,
                checkpoint_after,
                run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def fail_import_run(
    *,
    database_url: str,
    run_id: str,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        failed_item_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM import_run_items
            WHERE run_id = ? AND status = 'failed'
            """,
            (run_id,),
        ).fetchone()[0]
        skipped_item_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM import_run_items
            WHERE run_id = ? AND status = 'skipped'
            """,
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE import_runs
            SET
                status = 'failed',
                failed_item_count = ?,
                skipped_item_count = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
            """,
            (
                failed_item_count,
                skipped_item_count,
                run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def get_import_run(*, database_url: str, run_id: str) -> ImportRun:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT
                run_id,
                source_name,
                status,
                query,
                allowed_senders_json,
                max_results,
                fetched_message_count,
                imported_attachment_count,
                created_document_count,
                skipped_document_count,
                failed_item_count,
                skipped_item_count,
                checkpoint_before,
                checkpoint_after,
                retry_performed,
                retry_run_id,
                retried_message_count,
                resolved_message_count,
                failed_final_message_count,
                started_at,
                finished_at
            FROM import_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise LookupError(f"Import run not found: {run_id}")

    return ImportRun(
        run_id=row[0],
        source_name=row[1],
        status=row[2],
        query=row[3],
        allowed_senders=list(json.loads(row[4])),
        max_results=row[5],
        fetched_message_count=row[6],
        imported_attachment_count=row[7],
        created_document_count=row[8],
        skipped_document_count=row[9],
        failed_item_count=row[10],
        skipped_item_count=row[11],
        checkpoint_before=row[12],
        checkpoint_after=row[13],
        retry_performed=bool(row[14]),
        retry_run_id=row[15],
        retried_message_count=row[16],
        resolved_message_count=row[17],
        failed_final_message_count=row[18],
        started_at=row[19],
        finished_at=row[20],
    )


def list_import_runs(*, database_url: str, limit: int) -> list[ImportRun]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                run_id,
                source_name,
                status,
                query,
                allowed_senders_json,
                max_results,
                fetched_message_count,
                imported_attachment_count,
                created_document_count,
                skipped_document_count,
                failed_item_count,
                skipped_item_count,
                checkpoint_before,
                checkpoint_after,
                retry_performed,
                retry_run_id,
                retried_message_count,
                resolved_message_count,
                failed_final_message_count,
                started_at,
                finished_at
            FROM import_runs
            ORDER BY started_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()

    return [
        ImportRun(
            run_id=row[0],
            source_name=row[1],
            status=row[2],
            query=row[3],
            allowed_senders=list(json.loads(row[4])),
            max_results=row[5],
            fetched_message_count=row[6],
            imported_attachment_count=row[7],
            created_document_count=row[8],
            skipped_document_count=row[9],
            failed_item_count=row[10],
            skipped_item_count=row[11],
            checkpoint_before=row[12],
            checkpoint_after=row[13],
            retry_performed=bool(row[14]),
            retry_run_id=row[15],
            retried_message_count=row[16],
            resolved_message_count=row[17],
            failed_final_message_count=row[18],
            started_at=row[19],
            finished_at=row[20],
        )
        for row in rows
    ]


def get_last_successful_import_run_started_at(*, database_url: str) -> str | None:
    """Return the started_at of the most recent import run that actually
    completed (``succeeded`` or ``partial``).

    Runs that are still ``running`` or that ended ``failed`` are ignored so a
    transient import failure does not advance the worker's import cadence gate
    and defer the next attempt by a full interval.
    """
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT started_at
            FROM import_runs
            WHERE status IN ('succeeded', 'partial')
            ORDER BY started_at DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()
    return row[0] if row else None


def list_import_run_items(
    *,
    database_url: str,
    run_id: str,
    status: str | None = None,
    item_type: str | None = None,
) -> list[ImportRunItem]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        query = """
            SELECT
                id,
                run_id,
                item_type,
                item_key,
                message_id,
                attachment_id,
                link_url,
                status,
                detail_code,
                detail_message,
                document_key,
                message_internal_date,
                created_at
            FROM import_run_items
            WHERE run_id = ?
        """
        parameters: list[object] = [run_id]
        if status is not None:
            query += " AND status = ?"
            parameters.append(status)
        if item_type is not None:
            query += " AND item_type = ?"
            parameters.append(item_type)
        query += " ORDER BY id"
        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()

    return [_build_import_run_item(row) for row in rows]


def list_import_items(
    *,
    database_url: str,
    limit: int,
    status: str | None = None,
    item_type: str | None = None,
) -> list[ImportRunItem]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        query = """
            SELECT
                id,
                run_id,
                item_type,
                item_key,
                message_id,
                attachment_id,
                link_url,
                status,
                detail_code,
                detail_message,
                document_key,
                message_internal_date,
                created_at
            FROM import_run_items
            WHERE 1 = 1
        """
        parameters: list[object] = []
        if status is not None:
            query += " AND status = ?"
            parameters.append(status)
        if item_type is not None:
            query += " AND item_type = ?"
            parameters.append(item_type)
        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(limit)
        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()

    return [_build_import_run_item(row) for row in rows]


def _build_import_run_item(row) -> ImportRunItem:
    return [
        ImportRunItem(
            id=row[0],
            run_id=row[1],
            item_type=row[2],
            item_key=row[3],
            message_id=row[4],
            attachment_id=row[5],
            link_url=row[6],
            status=row[7],
            detail_code=row[8],
            detail_message=row[9],
            document_key=row[10],
            message_internal_date=row[11],
            created_at=row[12],
        )
    ][0]


def get_import_checkpoint(
    *,
    database_url: str,
    source_name: str,
    checkpoint_type: str,
) -> str | None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT checkpoint_value
            FROM import_checkpoints
            WHERE source_name = ? AND checkpoint_type = ?
            """,
            (source_name, checkpoint_type),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return row[0]


def set_import_checkpoint(
    *,
    database_url: str,
    source_name: str,
    checkpoint_type: str,
    checkpoint_value: str,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            INSERT INTO import_checkpoints (
                source_name,
                checkpoint_type,
                checkpoint_value
            ) VALUES (?, ?, ?)
            ON CONFLICT(source_name, checkpoint_type) DO UPDATE SET
                checkpoint_value = excluded.checkpoint_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (source_name, checkpoint_type, checkpoint_value),
        )
        connection.commit()
    finally:
        connection.close()


def mark_failed_message_pending(
    *,
    database_url: str,
    message_id: str,
    source_name: str,
    message_internal_date: str,
    run_id: str,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        existing = connection.execute(
            """
            SELECT retry_state, retry_attempt_count
            FROM failed_messages
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        if existing is None:
            retry_attempt_count = 0
        else:
            retry_attempt_count = existing[1]
            if existing[0] != "pending":
                retry_attempt_count += 1

        connection.execute(
            """
            INSERT INTO failed_messages (
                message_id,
                source_name,
                message_internal_date,
                retry_state,
                retry_attempt_count,
                last_run_id
            ) VALUES (?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                source_name = excluded.source_name,
                message_internal_date = excluded.message_internal_date,
                retry_state = 'pending',
                retry_attempt_count = ?,
                last_run_id = excluded.last_run_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                message_id,
                source_name,
                message_internal_date,
                retry_attempt_count,
                run_id,
                retry_attempt_count,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def mark_failed_message_resolved(
    *,
    database_url: str,
    message_id: str,
    run_id: str,
) -> None:
    _update_failed_message_state(
        database_url=database_url,
        message_id=message_id,
        retry_state="resolved",
        run_id=run_id,
    )


def mark_failed_message_failed_final(
    *,
    database_url: str,
    message_id: str,
    run_id: str,
) -> None:
    _update_failed_message_state(
        database_url=database_url,
        message_id=message_id,
        retry_state="failed_final",
        run_id=run_id,
    )


def list_failed_messages_for_retry(
    *,
    database_url: str,
    source_name: str,
) -> list[FailedMessage]:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        rows = connection.execute(
            """
            SELECT
                message_id,
                source_name,
                message_internal_date,
                retry_state,
                retry_attempt_count,
                last_run_id,
                created_at,
                updated_at
            FROM failed_messages
            WHERE source_name = ? AND retry_state = 'pending' AND retry_attempt_count < 1
            ORDER BY message_internal_date DESC, message_id DESC
            """,
            (source_name,),
        ).fetchall()
    finally:
        connection.close()

    return [
        FailedMessage(
            message_id=row[0],
            source_name=row[1],
            message_internal_date=row[2],
            retry_state=row[3],
            retry_attempt_count=row[4],
            last_run_id=row[5],
            created_at=row[6],
            updated_at=row[7],
        )
        for row in rows
    ]


def claim_failed_message_for_retry(
    *,
    database_url: str,
    message_id: str,
    run_id: str,
) -> bool:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT retry_state, retry_attempt_count
            FROM failed_messages
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        if row is None:
            return False
        if row[0] != "pending" or row[1] >= 1:
            return False

        connection.execute(
            """
            UPDATE failed_messages
            SET
                retry_attempt_count = retry_attempt_count + 1,
                last_run_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE message_id = ?
            """,
            (run_id, message_id),
        )
        connection.commit()
        return True
    finally:
        connection.close()


def _update_failed_message_state(
    *,
    database_url: str,
    message_id: str,
    retry_state: str,
    run_id: str,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE failed_messages
            SET
                retry_state = ?,
                last_run_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE message_id = ?
            """,
            (retry_state, run_id, message_id),
        )
        connection.commit()
    finally:
        connection.close()


def record_import_run_retry_summary(
    *,
    database_url: str,
    run_id: str,
    retry_run_id: str | None,
    retried_message_count: int,
    resolved_message_count: int,
    failed_final_message_count: int,
) -> None:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        connection.execute(
            """
            UPDATE import_runs
            SET
                retry_performed = ?,
                retry_run_id = ?,
                retried_message_count = ?,
                resolved_message_count = ?,
                failed_final_message_count = ?
            WHERE run_id = ?
            """,
            (
                1 if retry_run_id is not None or retried_message_count > 0 else 0,
                retry_run_id,
                retried_message_count,
                resolved_message_count,
                failed_final_message_count,
                run_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
