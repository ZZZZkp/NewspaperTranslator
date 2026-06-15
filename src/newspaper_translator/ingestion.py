from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
import re
import sqlite3
import unicodedata

from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.document_processing import create_document_processing_run
from newspaper_translator.documents import DocumentIdentity
from newspaper_translator.logging_utils import format_log_event

TRANSLATION_PREFIXES = ("【译】",)
TRANSLATED_FILENAME_PATTERNS = (
    "中文-华尔街日报",
    "中文-金融时报",
    "【译】the_economist_(web_edition)_0205.pdf",
)


@dataclass(frozen=True)
class GmailAttachment:
    attachment_id: str
    filename: str
    mime_type: str
    content_bytes: bytes = b""
    link_url: str | None = None

    @property
    def is_pdf(self) -> bool:
        return (
            self.mime_type == "application/pdf" or self.filename.lower().endswith(".pdf")
        ) and not _is_translated_pdf_filename(self.filename)


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    sender: str
    attachments: list[GmailAttachment]
    internal_date: str | None = None


@dataclass(frozen=True)
class ImportedDocument:
    document_key: str
    content_hash: str
    raw_path: Path
    was_created: bool


def select_target_messages(
    *,
    messages: list[GmailMessage],
    allowed_senders: set[str],
) -> list[GmailMessage]:
    return [
        message
        for message in messages
        if message.sender in allowed_senders and any(attachment.is_pdf for attachment in message.attachments)
    ]


def import_gmail_pdf_attachment(
    *,
    message: GmailMessage,
    attachment: GmailAttachment,
    storage_root: Path,
    database_url: str,
) -> ImportedDocument:
    if not attachment.is_pdf:
        raise ValueError(f"Attachment is not a PDF: {attachment.filename}")

    content_hash = hashlib.sha256(attachment.content_bytes).hexdigest()
    identity = DocumentIdentity.from_attachment(
        message_id=message.message_id,
        attachment_id=attachment.attachment_id,
        content_hash=content_hash,
    )
    filename_source_name = _extract_source_name_from_filename(attachment.filename)

    raw_path = _build_raw_pdf_path(
        storage_root=Path(storage_root),
        message_id=message.message_id,
        attachment_id=attachment.attachment_id,
        content_hash=content_hash,
        filename=attachment.filename,
    )

    database_path = sqlite_path_from_database_url(database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing_row = connection.execute(
            """
            SELECT document_key, raw_path
            FROM documents
            WHERE content_hash = ?
            ORDER BY created_at ASC, rowid ASC
            LIMIT 1
            """,
            (content_hash,),
        ).fetchone()
        if existing_row is not None:
            connection.commit()
            print(
                format_log_event(
                    level="INFO",
                    event="duplicate_document_reused",
                    service="worker",
                    details={
                        "content_hash": content_hash,
                        "canonical_document_key": existing_row[0],
                        "message_id": message.message_id,
                        "attachment_id": attachment.attachment_id,
                    },
                ),
                flush=True,
            )
            create_document_processing_run(
                database_url=database_url,
                document_key=existing_row[0],
            )
            return ImportedDocument(
                document_key=existing_row[0],
                content_hash=content_hash,
                raw_path=Path(existing_row[1]),
                was_created=False,
            )

        cursor = connection.execute(
            """
            INSERT INTO documents (
                document_key,
                source_name,
                source_message_id,
                source_attachment_id,
                sender,
                original_filename,
                content_hash,
                raw_path,
                import_status,
                source_message_internal_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.document_key,
                filename_source_name,
                message.message_id,
                attachment.attachment_id,
                message.sender,
                attachment.filename,
                content_hash,
                str(raw_path),
                "imported",
                message.internal_date,
            ),
        )
        was_created = cursor.rowcount == 1

        if was_created and not raw_path.exists():
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(attachment.content_bytes)

        connection.commit()
    finally:
        connection.close()

    create_document_processing_run(
        database_url=database_url,
        document_key=identity.document_key,
    )

    return ImportedDocument(
        document_key=identity.document_key,
        content_hash=content_hash,
        raw_path=raw_path,
        was_created=was_created,
    )


def import_selected_messages(
    *,
    messages: list[GmailMessage],
    allowed_senders: set[str],
    storage_root: Path,
    database_url: str,
) -> list[ImportedDocument]:
    imported_documents: list[ImportedDocument] = []
    for message in select_target_messages(
        messages=messages,
        allowed_senders=allowed_senders,
    ):
        for attachment in message.attachments:
            if not attachment.is_pdf:
                continue
            imported_documents.append(
                import_gmail_pdf_attachment(
                    message=message,
                    attachment=attachment,
                    storage_root=storage_root,
                    database_url=database_url,
                )
            )
    return imported_documents


def _build_raw_pdf_path(
    *,
    storage_root: Path,
    message_id: str,
    attachment_id: str,
    content_hash: str,
    filename: str,
) -> Path:
    suffix = Path(filename).suffix or ".pdf"
    sanitized_attachment_id = attachment_id.replace("/", "_")
    return (
        storage_root
        / "raw"
        / "gmail"
        / message_id
        / f"{sanitized_attachment_id}-{content_hash}{suffix}"
    )


def _is_translated_pdf_filename(filename: str) -> bool:
    base = Path(filename).name
    if base.startswith(TRANSLATION_PREFIXES):
        return True
    lowered_base = base.lower()
    return any(pattern in lowered_base for pattern in TRANSLATED_FILENAME_PATTERNS)


_ECONOMIST_EDITION_FILENAME_RE = re.compile(
    r"^TE[-_]\d{4}[-_]\d{1,2}[-_]\d{1,2}[-_]PDF[-_]WEB$",
    re.IGNORECASE,
)


def _is_economist_edition_filename(filename: str) -> bool:
    stem = unicodedata.normalize("NFKC", Path(filename).name)
    stem = Path(stem).stem
    stem = stem.removeprefix("【译】")
    return bool(_ECONOMIST_EDITION_FILENAME_RE.match(stem))


def _extract_source_name_from_filename(filename: str) -> str:
    if _is_economist_edition_filename(filename):
        return "经济学人"
    stem = Path(filename).name
    stem = Path(stem).stem
    full_date_match = re.search(
        r"^(?P<prefix>.*?)[-_](\d{4})[-_](\d{1,2})[-_](\d{1,2})$",
        stem,
    )
    if full_date_match and _is_valid_date_suffix(
        year=int(full_date_match.group(2)),
        month=int(full_date_match.group(3)),
        day=int(full_date_match.group(4)),
    ):
        prefix = full_date_match.group("prefix").rstrip("-_ ").strip()
        return prefix or stem
    month_day_match = re.search(r"^(?P<prefix>.*?)[-_](\d{1,2})[-_](\d{1,2})$", stem)
    if month_day_match and _is_valid_month_day_suffix(
        month=int(month_day_match.group(2)),
        day=int(month_day_match.group(3)),
    ):
        prefix = month_day_match.group("prefix").rstrip("-_ ").strip()
        return prefix or stem
    return stem


def _is_valid_date_suffix(*, year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _is_valid_month_day_suffix(*, month: int, day: int) -> bool:
    return _is_valid_date_suffix(year=2000, month=month, day=day)
