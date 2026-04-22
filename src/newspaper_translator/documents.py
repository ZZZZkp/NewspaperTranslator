from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentIdentity:
    message_id: str
    attachment_id: str
    content_hash: str
    document_key: str

    @classmethod
    def from_attachment(
        cls,
        *,
        message_id: str,
        attachment_id: str,
        content_hash: str,
    ) -> "DocumentIdentity":
        return cls(
            message_id=message_id,
            attachment_id=attachment_id,
            content_hash=content_hash,
            document_key=f"{message_id}:{attachment_id}:{content_hash}",
        )
