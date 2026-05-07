from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sqlite3

from newspaper_translator.article_store import (
    create_parse_run,
    finalize_parse_run,
    record_parse_run_result,
    update_parse_run_source_artifacts,
)
from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.logging_utils import format_log_event
from newspaper_translator.pdf import build_parse_result_from_mineru_markdown


@dataclass(frozen=True)
class StoredDocument:
    document_key: str
    original_filename: str
    raw_path: str
    source_message_internal_date: str | None


def persist_document_articles(
    *,
    database_url: str,
    document_key: str,
    output_root: Path,
    mineru_client,
    continuation_matcher,
    parser_name: str,
    parser_version: str,
    continuation_matcher_name: str,
    continuation_matcher_version: str,
):
    document = _get_document(database_url=database_url, document_key=document_key)
    parsed_document = mineru_client.parse_pdf(
        pdf_path=Path(document.raw_path),
        output_root=Path(output_root),
    )
    publication_date = resolve_publication_date(
        original_filename=document.original_filename,
        markdown_text=parsed_document.markdown_text,
        source_message_internal_date=document.source_message_internal_date,
        fallback_year=datetime.now().year,
    )

    parse_run = create_parse_run(
        database_url=database_url,
        document_key=document_key,
        parser_name=parser_name,
        parser_version=parser_version,
        publication_date=publication_date or "",
        continuation_matcher_name=continuation_matcher_name,
        continuation_matcher_version=continuation_matcher_version,
    )
    update_parse_run_source_artifacts(
        database_url=database_url,
        parse_run_id=parse_run.parse_run_id,
        mineru_batch_id=parsed_document.batch_id,
        mineru_file_id=parsed_document.file_id,
        markdown_path=str(parsed_document.markdown_path),
    )

    if not publication_date:
        error_message = (
            "Unable to resolve publication date from document filename or parsed markdown"
        )
        finalize_parse_run(
            database_url=database_url,
            parse_run_id=parse_run.parse_run_id,
            status="failed",
            error_message=error_message,
        )
        raise ValueError(error_message)

    parse_result = build_parse_result_from_mineru_markdown(
        parsed_document.markdown_text,
        continuation_matcher=continuation_matcher,
    )
    record_parse_run_result(
        database_url=database_url,
        parse_run_id=parse_run.parse_run_id,
        parse_result=parse_result,
        document_key=document_key,
        publication_date=publication_date,
    )
    finalize_parse_run(
        database_url=database_url,
        parse_run_id=parse_run.parse_run_id,
        status="succeeded",
    )

    return next(
        run
        for run in _list_parse_runs_for_document(
            database_url=database_url,
            document_key=document_key,
        )
        if run.parse_run_id == parse_run.parse_run_id
    )


def resolve_publication_date(
    *,
    original_filename: str,
    markdown_text: str,
    source_message_internal_date: str | None = None,
    fallback_year: int | None = None,
) -> str:
    filename_iso_date = _extract_iso_date_from_text(original_filename)
    if filename_iso_date:
        return filename_iso_date

    month_day_candidate_found, filename_month_day_date = _extract_month_day_date_from_filename(
        original_filename,
        source_message_internal_date=source_message_internal_date,
        fallback_year=fallback_year or datetime.now().year,
    )
    if month_day_candidate_found:
        return filename_month_day_date

    return _extract_written_date_from_text(markdown_text) or _extract_iso_date_from_text(
        markdown_text
    )


def _extract_iso_date_from_text(text: str) -> str:
    match = re.search(r"(\d{4})[-_/](\d{1,2})[-_/](\d{1,2})", text)
    if not match:
        return ""
    return _normalize_date_parts(
        year=int(match.group(1)),
        month=int(match.group(2)),
        day=int(match.group(3)),
    )


def _extract_written_date_from_text(text: str) -> str:
    match = re.search(
        r"\b("
        r"January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
        r")\s+(\d{1,2}),\s*(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""

    month_name = match.group(1).title()
    if month_name == "Sept":
        month_name = "Sep"
    parsed_date = datetime.strptime(
        f"{month_name} {match.group(2)} {match.group(3)}",
        "%b %d %Y" if len(month_name) <= 3 else "%B %d %Y",
    )
    return parsed_date.strftime("%Y-%m-%d")


def _extract_month_day_date_from_filename(
    filename: str,
    *,
    source_message_internal_date: str | None,
    fallback_year: int,
) -> tuple[bool, str]:
    stem = Path(filename).stem
    match = re.search(r"[-_](\d{1,2})[-_](\d{1,2})$", stem)
    if not match:
        return False, ""

    year = _year_from_message_internal_date(source_message_internal_date) or fallback_year
    try:
        resolved = _normalize_date_parts(
            year=year,
            month=int(match.group(1)),
            day=int(match.group(2)),
        )
    except ValueError:
        return True, ""

    _log_publication_date_resolution(
        event="publication_date_resolved",
        details={
            "original_filename": filename,
            "resolution_source": (
                "filename_month_day_gmail_year"
                if source_message_internal_date
                else "filename_month_day_fallback_year"
            ),
            "publication_date": resolved,
        },
    )
    if source_message_internal_date:
        gmail_date = datetime.fromtimestamp(
            int(source_message_internal_date) / 1000
        ).strftime("%Y-%m-%d")
        if gmail_date != resolved:
            _log_publication_date_resolution(
                event="publication_date_filename_gmail_mismatch",
                details={
                    "original_filename": filename,
                    "filename_publication_date": resolved,
                    "gmail_message_date": gmail_date,
                },
            )
    return True, resolved


def _normalize_date_parts(*, year: int, month: int, day: int) -> str:
    return datetime(year=year, month=month, day=day).strftime("%Y-%m-%d")


def _year_from_message_internal_date(message_internal_date: str | None) -> int | None:
    if not message_internal_date:
        return None
    return datetime.fromtimestamp(int(message_internal_date) / 1000).year


def _log_publication_date_resolution(*, event: str, details: dict[str, object]) -> None:
    print(
        format_log_event(
            level="INFO",
            event=event,
            service="worker",
            details=details,
        ),
        flush=True,
    )


def _get_document(*, database_url: str, document_key: str) -> StoredDocument:
    connection = sqlite3.connect(sqlite_path_from_database_url(database_url))
    try:
        row = connection.execute(
            """
            SELECT document_key, original_filename, raw_path, source_message_internal_date
            FROM documents
            WHERE document_key = ?
            """,
            (document_key,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise LookupError(f"Document not found: {document_key}")

    return StoredDocument(
        document_key=row[0],
        original_filename=row[1],
        raw_path=row[2],
        source_message_internal_date=row[3],
    )


def _list_parse_runs_for_document(*, database_url: str, document_key: str):
    from newspaper_translator.article_store import list_parse_runs

    return list_parse_runs(database_url=database_url, document_key=document_key)
