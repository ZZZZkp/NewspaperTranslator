from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3

from newspaper_translator.database import sqlite_path_from_database_url
from newspaper_translator.documents import DocumentIdentity
from newspaper_translator.tasks import ProcessingTask

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


def create_document_processing_task(*, document_key: str) -> ProcessingTask:
    return ProcessingTask.create(task_name=f"process-document:{document_key}")


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

    raw_path = _build_raw_pdf_path(
        storage_root=Path(storage_root),
        message_id=message.message_id,
        attachment_id=attachment.attachment_id,
        content_hash=content_hash,
        filename=attachment.filename,
    )

    database_path = sqlite_path_from_database_url(database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO documents (
                document_key,
                source_name,
                source_message_id,
                source_attachment_id,
                sender,
                original_filename,
                content_hash,
                raw_path,
                import_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.document_key,
                "gmail",
                message.message_id,
                attachment.attachment_id,
                message.sender,
                attachment.filename,
                content_hash,
                str(raw_path),
                "imported",
            ),
        )
        was_created = cursor.rowcount == 1

        if was_created and not raw_path.exists():
            raw_path.write_bytes(attachment.content_bytes)

        if was_created:
            task = create_document_processing_task(document_key=identity.document_key)
            connection.execute(
                """
                INSERT OR IGNORE INTO processing_tasks (task_name, status)
                VALUES (?, ?)
                """,
                (task.task_name, task.status),
            )

        connection.commit()
        return ImportedDocument(
            document_key=identity.document_key,
            content_hash=content_hash,
            raw_path=raw_path,
            was_created=was_created,
        )
    finally:
        connection.close()


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
