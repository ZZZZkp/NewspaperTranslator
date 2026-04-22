from dataclasses import dataclass

from newspaper_translator.tasks import ProcessingTask


@dataclass(frozen=True)
class GmailAttachment:
    attachment_id: str
    filename: str
    mime_type: str

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == "application/pdf" or self.filename.lower().endswith(".pdf")


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    sender: str
    attachments: list[GmailAttachment]


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
