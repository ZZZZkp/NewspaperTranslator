import base64
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import os
from email.utils import parseaddr
from pathlib import Path
import re
from urllib.parse import quote, urljoin, urlparse

from newspaper_translator.import_audit import (
    claim_failed_message_for_retry,
    create_import_run,
    fail_import_run,
    finalize_import_run,
    get_import_checkpoint,
    list_failed_messages_for_retry,
    list_import_run_items,
    mark_failed_message_failed_final,
    mark_failed_message_pending,
    mark_failed_message_resolved,
    record_import_run_item,
    record_import_run_retry_summary,
    set_import_checkpoint,
)
from newspaper_translator.ingestion import (
    GmailAttachment,
    GmailMessage,
    import_selected_messages,
    select_target_messages,
)


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@dataclass(frozen=True)
class GmailIntegrationConfig:
    oauth_client_secrets_path: Path
    oauth_token_path: Path
    allowed_senders: list[str]
    query: str
    label_ids: list[str]
    max_results: int
    include_spam_trash: bool
    user_id: str
    scopes: list[str]
    enable_body_links: bool
    allowed_link_domains: list[str]
    download_link_keywords: list[str]
    proxy_url: str | None


@dataclass(frozen=True)
class GmailImportSummary:
    run_id: str
    status: str
    retry_performed: bool
    retry_run_id: str | None
    retried_message_count: int
    resolved_message_count: int
    failed_final_message_count: int
    fetched_message_count: int
    imported_attachment_count: int
    created_document_count: int
    skipped_document_count: int


@dataclass(frozen=True)
class GmailRetrySummary:
    run_id: str | None
    retried_message_count: int
    resolved_message_count: int
    failed_final_message_count: int


def load_gmail_integration_config(path: Path) -> GmailIntegrationConfig:
    config_path = Path(path)
    payload = json.loads(config_path.read_text())

    return GmailIntegrationConfig(
        oauth_client_secrets_path=_resolve_config_path(
            config_path,
            payload["oauth_client_secrets_path"],
        ),
        oauth_token_path=_resolve_config_path(
            config_path,
            payload["oauth_token_path"],
        ),
        allowed_senders=list(payload["allowed_senders"]),
        query=payload["query"],
        label_ids=list(payload.get("label_ids", [])),
        max_results=int(payload.get("max_results", 25)),
        include_spam_trash=bool(payload.get("include_spam_trash", False)),
        user_id=payload.get("user_id", "me"),
        scopes=list(payload.get("scopes", [GMAIL_READONLY_SCOPE])),
        enable_body_links=bool(payload.get("enable_body_links", True)),
        allowed_link_domains=list(payload.get("allowed_link_domains", [])),
        download_link_keywords=list(payload.get("download_link_keywords", ["download", "pdf"])),
        proxy_url=payload.get("proxy_url"),
    )


def import_from_gmail(
    *,
    config_path: Path,
    storage_root: Path,
    database_url: str,
    service=None,
    downloader=None,
) -> GmailImportSummary:
    config = load_gmail_integration_config(config_path)
    checkpoint_before = get_import_checkpoint(
        database_url=database_url,
        source_name="gmail",
        checkpoint_type="message_internal_date",
    )
    import_run = create_import_run(
        database_url=database_url,
        source_name="gmail",
        query=config.query,
        allowed_senders=config.allowed_senders,
        max_results=config.max_results,
        checkpoint_before=checkpoint_before,
    )
    gmail_service = service or build_gmail_service(config)
    link_downloader = downloader or HttpLinkDownloader()
    try:
        messages = fetch_gmail_messages(
            config=config,
            service=gmail_service,
            downloader=link_downloader,
            query_override=_build_incremental_query(
                base_query=config.query,
                checkpoint_value=checkpoint_before,
            ),
            body_link_audit_callback=lambda **kwargs: _record_body_link_audit_item(
                database_url=database_url,
                run_id=import_run.run_id,
                **kwargs,
            ),
        )
        selected_messages, imported_documents = _process_messages_into_audit_and_documents(
            database_url=database_url,
            run_id=import_run.run_id,
            messages=messages,
            allowed_senders=set(config.allowed_senders),
            storage_root=storage_root,
            database_url_for_import=database_url,
        )
        _update_failed_message_tracking(
            database_url=database_url,
            run_id=import_run.run_id,
            messages=messages,
        )

        created_document_count = sum(1 for document in imported_documents if document.was_created)
        imported_attachment_count = len(imported_documents)
        checkpoint_after = _max_message_internal_date(selected_messages)
        finalize_import_run(
            database_url=database_url,
            run_id=import_run.run_id,
            fetched_message_count=len(messages),
            imported_attachment_count=imported_attachment_count,
            created_document_count=created_document_count,
            skipped_document_count=imported_attachment_count - created_document_count,
            checkpoint_after=checkpoint_after,
        )
        if checkpoint_after is not None:
            set_import_checkpoint(
                database_url=database_url,
                source_name="gmail",
                checkpoint_type="message_internal_date",
                checkpoint_value=checkpoint_after,
            )
        retry_summary = retry_failed_gmail_messages(
            config_path=config_path,
            storage_root=storage_root,
            database_url=database_url,
            service=gmail_service,
            downloader=link_downloader,
        )
        record_import_run_retry_summary(
            database_url=database_url,
            run_id=import_run.run_id,
            retry_run_id=retry_summary.run_id,
            retried_message_count=retry_summary.retried_message_count,
            resolved_message_count=retry_summary.resolved_message_count,
            failed_final_message_count=retry_summary.failed_final_message_count,
        )
        return GmailImportSummary(
            run_id=import_run.run_id,
            status="partial"
            if _has_failed_items(database_url=database_url, run_id=import_run.run_id)
            else "succeeded",
            retry_performed=retry_summary.retried_message_count > 0,
            retry_run_id=retry_summary.run_id,
            retried_message_count=retry_summary.retried_message_count,
            resolved_message_count=retry_summary.resolved_message_count,
            failed_final_message_count=retry_summary.failed_final_message_count,
            fetched_message_count=len(messages),
            imported_attachment_count=imported_attachment_count,
            created_document_count=created_document_count,
            skipped_document_count=imported_attachment_count - created_document_count,
        )
    except Exception:
        fail_import_run(
            database_url=database_url,
            run_id=import_run.run_id,
        )
        raise


def retry_failed_gmail_messages(
    *,
    config_path: Path,
    storage_root: Path,
    database_url: str,
    service=None,
    downloader=None,
) -> GmailRetrySummary:
    config = load_gmail_integration_config(config_path)
    pending_messages = list_failed_messages_for_retry(
        database_url=database_url,
        source_name="gmail",
    )
    if not pending_messages:
        return GmailRetrySummary(
            run_id=None,
            retried_message_count=0,
            resolved_message_count=0,
            failed_final_message_count=0,
        )

    gmail_service = service or build_gmail_service(config)
    link_downloader = downloader or HttpLinkDownloader()
    retry_run = create_import_run(
        database_url=database_url,
        source_name="gmail",
        query="retry-failures",
        allowed_senders=config.allowed_senders,
        max_results=len(pending_messages),
        checkpoint_before=get_import_checkpoint(
            database_url=database_url,
            source_name="gmail",
            checkpoint_type="message_internal_date",
        ),
    )

    fetched_message_count = 0
    imported_attachment_count = 0
    created_document_count = 0
    skipped_document_count = 0
    resolved_message_count = 0
    failed_final_message_count = 0

    try:
        for failed_message in pending_messages:
            if not claim_failed_message_for_retry(
                database_url=database_url,
                message_id=failed_message.message_id,
                run_id=retry_run.run_id,
            ):
                continue
            try:
                message = _fetch_gmail_message(
                    config=config,
                    service=gmail_service,
                    downloader=link_downloader,
                    message_id=failed_message.message_id,
                    body_link_audit_callback=lambda **kwargs: _record_body_link_audit_item(
                        database_url=database_url,
                        run_id=retry_run.run_id,
                        **kwargs,
                    ),
                )
                fetched_message_count += 1
                selected_messages, imported_documents = _process_messages_into_audit_and_documents(
                    database_url=database_url,
                    run_id=retry_run.run_id,
                    messages=[message],
                    allowed_senders=set(config.allowed_senders),
                    storage_root=storage_root,
                    database_url_for_import=database_url,
                )
                imported_attachment_count += len(imported_documents)
                created_document_count += sum(
                    1 for document in imported_documents if document.was_created
                )
                skipped_document_count += len(imported_documents) - sum(
                    1 for document in imported_documents if document.was_created
                )
                if _message_has_failed_items(
                    database_url=database_url,
                    run_id=retry_run.run_id,
                    message_id=message.message_id,
                ):
                    mark_failed_message_failed_final(
                        database_url=database_url,
                        message_id=message.message_id,
                        run_id=retry_run.run_id,
                    )
                    failed_final_message_count += 1
                else:
                    mark_failed_message_resolved(
                        database_url=database_url,
                        message_id=message.message_id,
                        run_id=retry_run.run_id,
                    )
                    resolved_message_count += 1
            except Exception as exc:
                record_import_run_item(
                    database_url=database_url,
                    run_id=retry_run.run_id,
                    item_type="message",
                    item_key=f"message:{failed_message.message_id}",
                    message_id=failed_message.message_id,
                    attachment_id=None,
                    link_url=None,
                    status="failed",
                    detail_code="retry_message_fetch_failed",
                    detail_message=str(exc),
                    document_key=None,
                    message_internal_date=failed_message.message_internal_date,
                )
                mark_failed_message_failed_final(
                    database_url=database_url,
                    message_id=failed_message.message_id,
                    run_id=retry_run.run_id,
                )
                failed_final_message_count += 1

        finalize_import_run(
            database_url=database_url,
            run_id=retry_run.run_id,
            fetched_message_count=fetched_message_count,
            imported_attachment_count=imported_attachment_count,
            created_document_count=created_document_count,
            skipped_document_count=skipped_document_count,
        )
        return GmailRetrySummary(
            run_id=retry_run.run_id,
            retried_message_count=resolved_message_count + failed_final_message_count,
            resolved_message_count=resolved_message_count,
            failed_final_message_count=failed_final_message_count,
        )
    except Exception:
        fail_import_run(
            database_url=database_url,
            run_id=retry_run.run_id,
        )
        raise


def build_gmail_service(config: GmailIntegrationConfig):
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    if config.oauth_token_path.exists():
        credentials = Credentials.from_authorized_user_file(
            str(config.oauth_token_path),
            config.scopes,
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.oauth_client_secrets_path),
                config.scopes,
            )
            credentials = flow.run_local_server(port=0)

        config.oauth_token_path.parent.mkdir(parents=True, exist_ok=True)
        config.oauth_token_path.write_text(credentials.to_json())

    proxy_url = _resolve_proxy_url(config)
    session = AuthorizedSession(credentials)
    if proxy_url:
        session.proxies.update(
            {
                "http": proxy_url,
                "https": proxy_url,
            }
        )
    return RequestsGmailService(session=session)


def fetch_gmail_messages(
    *,
    config: GmailIntegrationConfig,
    service,
    downloader,
    query_override: str | None = None,
    body_link_audit_callback=None,
) -> list[GmailMessage]:
    list_kwargs = {
        "userId": config.user_id,
        "q": query_override or config.query,
        "maxResults": config.max_results,
        "includeSpamTrash": config.include_spam_trash,
    }
    if config.label_ids:
        list_kwargs["labelIds"] = config.label_ids

    list_response = service.users().messages().list(**list_kwargs).execute()
    messages: list[GmailMessage] = []
    for message_ref in list_response.get("messages", []):
        messages.append(
            _fetch_gmail_message(
                config=config,
                service=service,
                downloader=downloader,
                message_id=message_ref["id"],
                body_link_audit_callback=body_link_audit_callback,
            )
        )
    return messages


def _fetch_gmail_message(
    *,
    config: GmailIntegrationConfig,
    service,
    downloader,
    message_id: str,
    body_link_audit_callback=None,
) -> GmailMessage:
    full_message = service.users().messages().get(
        userId=config.user_id,
        id=message_id,
        format="full",
    ).execute()
    payload = full_message.get("payload", {})
    internal_date = str(full_message.get("internalDate", "") or "")
    sender = _extract_sender(payload.get("headers", []))
    attachments = _extract_pdf_attachments(
        service=service,
        user_id=config.user_id,
        message_id=message_id,
        payload=payload,
    )
    if config.enable_body_links:
        attachments.extend(
            _extract_pdf_links_from_message_body(
                payload=payload,
                downloader=downloader,
                allowed_domains=set(config.allowed_link_domains),
                download_link_keywords=config.download_link_keywords,
                message_id=message_id,
                message_internal_date=internal_date,
                body_link_audit_callback=body_link_audit_callback,
            )
        )
    return GmailMessage(
        message_id=message_id,
        sender=sender,
        attachments=attachments,
        internal_date=internal_date,
    )


def _extract_sender(headers: list[dict[str, str]]) -> str:
    for header in headers:
        if header.get("name", "").lower() == "from":
            _, email_address = parseaddr(header.get("value", ""))
            return email_address or header.get("value", "")
    return ""


def _extract_pdf_attachments(
    *,
    service,
    user_id: str,
    message_id: str,
    payload: dict[str, object],
) -> list[GmailAttachment]:
    attachments: list[GmailAttachment] = []
    for part in _iter_message_parts(payload):
        filename = part.get("filename", "")
        mime_type = part.get("mimeType", "application/octet-stream")
        if not filename:
            continue
        if mime_type != "application/pdf" and not str(filename).lower().endswith(".pdf"):
            continue

        body = part.get("body", {})
        attachment_id = body.get("attachmentId") or part.get("partId") or filename
        data = body.get("data")
        if attachment_id and not data and body.get("attachmentId"):
            attachment_response = service.users().messages().attachments().get(
                userId=user_id,
                messageId=message_id,
                id=attachment_id,
            ).execute()
            data = attachment_response.get("data", "")

        attachments.append(
            GmailAttachment(
                attachment_id=str(attachment_id),
                filename=str(filename),
                mime_type=str(mime_type),
                content_bytes=_decode_gmail_base64(data or ""),
            )
        )
    return attachments


def _extract_pdf_links_from_message_body(
    *,
    payload: dict[str, object],
    downloader,
    allowed_domains: set[str],
    download_link_keywords: list[str],
    message_id: str,
    message_internal_date: str,
    body_link_audit_callback=None,
) -> list[GmailAttachment]:
    import requests

    attachments: list[GmailAttachment] = []
    seen_urls: set[str] = set()

    for mime_type, text in _extract_message_bodies(payload):
        candidate_urls = _extract_candidate_urls(text=text, mime_type=mime_type)
        for url in candidate_urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            if allowed_domains and not _is_allowed_domain(url, allowed_domains):
                _emit_body_link_audit(
                    body_link_audit_callback,
                    message_id=message_id,
                    message_internal_date=message_internal_date,
                    link_url=url,
                    status="skipped",
                    detail_code="link_domain_not_allowed",
                    detail_message="Link domain is not in allowed_link_domains.",
                )
                continue

            try:
                attachment = _build_attachment_from_url(
                    url=url,
                    downloader=downloader,
                    download_link_keywords=download_link_keywords,
                )
            except requests.RequestException as exc:
                _emit_body_link_audit(
                    body_link_audit_callback,
                    message_id=message_id,
                    message_internal_date=message_internal_date,
                    link_url=url,
                    status="failed",
                    detail_code="link_fetch_failed",
                    detail_message=str(exc),
                )
                continue
            if attachment is not None:
                attachments.append(attachment)
            else:
                _emit_body_link_audit(
                    body_link_audit_callback,
                    message_id=message_id,
                    message_internal_date=message_internal_date,
                    link_url=url,
                    status="skipped",
                    detail_code="link_not_importable",
                    detail_message="No PDF download target was found for the link.",
                )

    return attachments


def _process_messages_into_audit_and_documents(
    *,
    database_url: str,
    run_id: str,
    messages: list[GmailMessage],
    allowed_senders: set[str],
    storage_root: Path,
    database_url_for_import: str,
) -> tuple[list[GmailMessage], list]:
    _record_message_and_skipped_source_items(
        database_url=database_url,
        run_id=run_id,
        messages=messages,
        allowed_senders=allowed_senders,
    )
    imported_documents = import_selected_messages(
        messages=messages,
        allowed_senders=allowed_senders,
        storage_root=storage_root,
        database_url=database_url_for_import,
    )
    selected_messages = select_target_messages(
        messages=messages,
        allowed_senders=allowed_senders,
    )
    _record_imported_document_items(
        database_url=database_url,
        run_id=run_id,
        messages=selected_messages,
        imported_documents=imported_documents,
    )
    return selected_messages, imported_documents


def _record_message_and_skipped_source_items(
    *,
    database_url: str,
    run_id: str,
    messages: list[GmailMessage],
    allowed_senders: set[str],
) -> None:
    for message in messages:
        is_allowed_sender = message.sender in allowed_senders
        record_import_run_item(
            database_url=database_url,
            run_id=run_id,
            item_type="message",
            item_key=f"message:{message.message_id}",
            message_id=message.message_id,
            attachment_id=None,
            link_url=None,
            status="succeeded" if is_allowed_sender else "skipped",
            detail_code="message_selected" if is_allowed_sender else "sender_not_allowed",
            detail_message=(
                "Message sender matched allowed_senders."
                if is_allowed_sender
                else "Message sender did not match allowed_senders."
            ),
            document_key=None,
            message_internal_date=message.internal_date,
        )
        if is_allowed_sender:
            continue
        for attachment in message.attachments:
            item_type = "body_link" if attachment.attachment_id.startswith("link:") else "attachment"
            record_import_run_item(
                database_url=database_url,
                run_id=run_id,
                item_type=item_type,
                item_key=_build_import_item_key(
                    message_id=message.message_id,
                    attachment=attachment,
                ),
                message_id=message.message_id,
                attachment_id=attachment.attachment_id,
                link_url=_link_url_from_attachment(attachment),
                status="skipped",
                detail_code="sender_not_allowed",
                detail_message="Item skipped because sender is not allowed.",
                document_key=None,
                message_internal_date=message.internal_date,
            )


def _record_imported_document_items(
    *,
    database_url: str,
    run_id: str,
    messages: list[GmailMessage],
    imported_documents,
) -> None:
    imported_document_iter = iter(imported_documents)
    for message in messages:
        for attachment in message.attachments:
            imported_document = next(imported_document_iter)
            was_created = imported_document.was_created
            record_import_run_item(
                database_url=database_url,
                run_id=run_id,
                item_type="body_link" if attachment.attachment_id.startswith("link:") else "attachment",
                item_key=_build_import_item_key(
                    message_id=message.message_id,
                    attachment=attachment,
                ),
                message_id=message.message_id,
                attachment_id=attachment.attachment_id,
                link_url=_link_url_from_attachment(attachment),
                status="succeeded" if was_created else "skipped",
                detail_code="document_created" if was_created else "duplicate_document",
                detail_message=(
                    "Document was created from imported item."
                    if was_created
                    else "Item matched an existing imported document."
                ),
                document_key=imported_document.document_key,
                message_internal_date=message.internal_date,
            )


def _record_body_link_audit_item(
    *,
    database_url: str,
    run_id: str,
    message_id: str,
    message_internal_date: str,
    link_url: str,
    status: str,
    detail_code: str,
    detail_message: str,
) -> None:
    record_import_run_item(
        database_url=database_url,
        run_id=run_id,
        item_type="body_link",
        item_key=f"message:{message_id}:body_link:{link_url}",
        message_id=message_id,
        attachment_id=f"link:{link_url}",
        link_url=link_url,
        status=status,
        detail_code=detail_code,
        detail_message=detail_message,
        document_key=None,
        message_internal_date=message_internal_date,
    )


def _emit_body_link_audit(
    body_link_audit_callback,
    *,
    message_id: str,
    message_internal_date: str,
    link_url: str,
    status: str,
    detail_code: str,
    detail_message: str,
) -> None:
    if body_link_audit_callback is None:
        return
    body_link_audit_callback(
        message_id=message_id,
        message_internal_date=message_internal_date,
        link_url=link_url,
        status=status,
        detail_code=detail_code,
        detail_message=detail_message,
    )


def _build_import_item_key(*, message_id: str, attachment: GmailAttachment) -> str:
    if attachment.attachment_id.startswith("link:"):
        return f"message:{message_id}:body_link:{attachment.attachment_id.removeprefix('link:')}"
    return f"message:{message_id}:attachment:{attachment.attachment_id}"


def _link_url_from_attachment(attachment: GmailAttachment) -> str | None:
    if attachment.attachment_id.startswith("link:"):
        return attachment.attachment_id.removeprefix("link:")
    return None


def _build_incremental_query(*, base_query: str, checkpoint_value: str | None) -> str:
    if not checkpoint_value:
        return base_query

    seconds = int(int(checkpoint_value) / 1000)
    checkpoint_clause = f"after:{seconds}"
    if not base_query.strip():
        return checkpoint_clause
    return f"{base_query} {checkpoint_clause}"


def _max_message_internal_date(messages: list[GmailMessage]) -> str | None:
    internal_dates = [
        message.internal_date
        for message in messages
        if message.internal_date
    ]
    if not internal_dates:
        return None
    return max(internal_dates)


def _update_failed_message_tracking(
    *,
    database_url: str,
    run_id: str,
    messages: list[GmailMessage],
) -> None:
    messages_by_id = {message.message_id: message for message in messages}
    failed_items = list_import_run_items(
        database_url=database_url,
        run_id=run_id,
        status="failed",
    )
    failed_message_ids = {
        item.message_id
        for item in failed_items
        if item.message_id
    }

    for message_id in failed_message_ids:
        message = messages_by_id.get(message_id)
        if message is None or not message.internal_date:
            continue
        mark_failed_message_pending(
            database_url=database_url,
            message_id=message_id,
            source_name="gmail",
            message_internal_date=message.internal_date,
            run_id=run_id,
        )

    for message in messages:
        if message.message_id in failed_message_ids:
            continue
        mark_failed_message_resolved(
            database_url=database_url,
            message_id=message.message_id,
            run_id=run_id,
        )


def _message_has_failed_items(
    *,
    database_url: str,
    run_id: str,
    message_id: str,
) -> bool:
    return bool(
        list_import_run_items(
            database_url=database_url,
            run_id=run_id,
            status="failed",
        )
        and [
            item
            for item in list_import_run_items(
                database_url=database_url,
                run_id=run_id,
                status="failed",
            )
            if item.message_id == message_id
        ]
    )


def _has_failed_items(*, database_url: str, run_id: str) -> bool:
    return bool(list_import_run_items(database_url=database_url, run_id=run_id, status="failed"))


def _extract_message_bodies(payload: dict[str, object]) -> list[tuple[str, str]]:
    bodies: list[tuple[str, str]] = []
    mime_type = str(payload.get("mimeType", ""))
    body = payload.get("body", {})
    body_data = body.get("data")
    if body_data and mime_type in {"text/plain", "text/html"}:
        bodies.append((mime_type, _decode_gmail_base64(body_data).decode("utf-8", errors="replace")))

    for part in payload.get("parts", []):
        bodies.extend(_extract_message_bodies(part))

    return bodies


def _extract_candidate_urls(*, text: str, mime_type: str) -> list[str]:
    if mime_type == "text/html":
        parser = _AnchorParser()
        parser.feed(text)
        return parser.hrefs
    return re.findall(r"https?://[^\s<>\"]+", text)


def _is_allowed_domain(url: str, allowed_domains: set[str]) -> bool:
    hostname = urlparse(url).hostname or ""
    return hostname in allowed_domains


def _build_attachment_from_url(
    *,
    url: str,
    downloader,
    download_link_keywords: list[str],
) -> GmailAttachment | None:
    if _looks_like_pdf_url(url):
        return GmailAttachment(
            attachment_id=f"link:{url}",
            filename=_filename_from_url(url),
            mime_type="application/pdf",
            content_bytes=downloader.download_binary(url),
        )

    resolved_download_url = _resolve_download_url(
        url=url,
        downloader=downloader,
    )
    if resolved_download_url:
        return GmailAttachment(
            attachment_id=f"link:{resolved_download_url}",
            filename=_filename_from_url(resolved_download_url),
            mime_type="application/pdf",
            content_bytes=downloader.download_binary(resolved_download_url),
        )

    direct_pdf_bytes = _try_download_direct_pdf(
        url=url,
        downloader=downloader,
    )
    if direct_pdf_bytes is not None:
        return GmailAttachment(
            attachment_id=f"link:{url}",
            filename=_filename_from_url(url),
            mime_type="application/pdf",
            content_bytes=direct_pdf_bytes,
        )

    html = downloader.fetch_html(url)
    download_url = _find_download_link_in_html(
        page_url=url,
        html=html,
        download_link_keywords=download_link_keywords,
    )
    if not download_url:
        return None

    return GmailAttachment(
        attachment_id=f"link:{download_url}",
        filename=_filename_from_url(download_url),
        mime_type="application/pdf",
        content_bytes=downloader.download_binary(download_url),
    )


def _resolve_download_url(
    *,
    url: str,
    downloader,
) -> str | None:
    resolver = getattr(downloader, "resolve_download_url", None)
    if not callable(resolver):
        return None
    return resolver(url)


def _try_download_direct_pdf(
    *,
    url: str,
    downloader,
) -> bytes | None:
    if not _is_qq_mail_landing_page(url):
        return None

    content = downloader.download_binary(url)
    if content.startswith(b"%PDF"):
        return content
    return None


def _find_download_link_in_html(
    *,
    page_url: str,
    html: str,
    download_link_keywords: list[str],
) -> str | None:
    parser = _AnchorParser()
    parser.feed(html)
    lowered_keywords = [keyword.lower() for keyword in download_link_keywords]

    for href, text in parser.links:
        absolute_url = urljoin(page_url, href)
        if _looks_like_pdf_url(absolute_url):
            return absolute_url
        lowered_text = text.lower()
        if any(keyword in lowered_text for keyword in lowered_keywords):
            return absolute_url

    return None


def _looks_like_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    filename = Path(path).name
    if not filename:
        return "download.pdf"
    if Path(filename).suffix:
        return filename
    return f"{filename}.pdf"


def _iter_message_parts(payload: dict[str, object]) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    nested_parts = payload.get("parts", [])
    for part in nested_parts:
        parts.append(part)
        parts.extend(_iter_message_parts(part))
    return parts


def _decode_gmail_base64(data: str) -> bytes:
    if not data:
        return b""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _resolve_config_path(config_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def _resolve_proxy_url(config: GmailIntegrationConfig) -> str | None:
    if config.proxy_url:
        return config.proxy_url

    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value:
            return value

    return None


class HttpLinkDownloader:
    def download_binary(self, url: str) -> bytes:
        import requests

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content

    def fetch_html(self, url: str) -> str:
        import requests

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text

    def resolve_download_url(self, url: str) -> str | None:
        if not _is_qq_mail_landing_page(url):
            return None

        import requests

        response = requests.post(url, data={"f": "json"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        body = payload.get("body", {})
        if not isinstance(body, dict):
            return None

        candidate_url = body.get("url") or body.get("download_url") or payload.get("download_url")
        if not candidate_url:
            return None
        return str(candidate_url)


def _is_qq_mail_landing_page(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == "wx.mail.qq.com" and parsed.path == "/ftn/download"


class RequestsGmailService:
    def __init__(self, *, session, base_url: str = "https://gmail.googleapis.com/gmail/v1") -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    def users(self):
        return _RequestsUsersResource(
            session=self._session,
            base_url=self._base_url,
        )


class _RequestsUsersResource:
    def __init__(self, *, session, base_url: str) -> None:
        self._session = session
        self._base_url = base_url

    def messages(self):
        return _RequestsMessagesResource(
            session=self._session,
            base_url=self._base_url,
        )


class _RequestsMessagesResource:
    def __init__(self, *, session, base_url: str) -> None:
        self._session = session
        self._base_url = base_url

    def list(self, **kwargs):
        user_id = kwargs.pop("userId")
        return _RequestsApiRequest(
            session=self._session,
            method="GET",
            url=f"{self._base_url}/users/{quote(str(user_id), safe='')}/messages",
            params=kwargs,
        )

    def get(self, *, userId: str, id: str, format: str):
        return _RequestsApiRequest(
            session=self._session,
            method="GET",
            url=f"{self._base_url}/users/{quote(userId, safe='')}/messages/{quote(id, safe='')}",
            params={"format": format},
        )

    def attachments(self):
        return _RequestsAttachmentsResource(
            session=self._session,
            base_url=self._base_url,
        )


class _RequestsAttachmentsResource:
    def __init__(self, *, session, base_url: str) -> None:
        self._session = session
        self._base_url = base_url

    def get(self, *, userId: str, messageId: str, id: str):
        return _RequestsApiRequest(
            session=self._session,
            method="GET",
            url=(
                f"{self._base_url}/users/{quote(userId, safe='')}/messages/"
                f"{quote(messageId, safe='')}/attachments/{quote(id, safe='')}"
            ),
        )


class _RequestsApiRequest:
    def __init__(
        self,
        *,
        session,
        method: str,
        url: str,
        params: dict[str, object] | None = None,
    ) -> None:
        self._session = session
        self._method = method
        self._url = url
        self._params = params

    def execute(self):
        response = self._session.request(
            self._method,
            self._url,
            params=self._params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self._current_href = value
                self.hrefs.append(value)
                self._current_text_parts = []
                return

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = "".join(self._current_text_parts).strip()
        self.links.append((self._current_href, text))
        self._current_href = None
        self._current_text_parts = []
