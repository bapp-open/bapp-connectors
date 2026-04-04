"""
Gmail mappers — convert between framework DTOs and Gmail API payloads.

Gmail uses base64url encoding (RFC 4648 section 5) for message bodies
and attachments. Standard base64 will NOT work — always use
``base64.urlsafe_b64encode`` / ``base64.urlsafe_b64decode``.
"""

from __future__ import annotations

import base64
import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    DeliveryReport,
    DeliveryStatus,
    EmailAddress,
    EmailAttachmentContent,
    EmailAttachmentInfo,
    EmailDetail,
    EmailSummary,
)

if TYPE_CHECKING:
    from bapp_connectors.core.dto import OutboundMessage

logger = logging.getLogger(__name__)

# ── Label / Folder mapping ──

_FOLDER_TO_LABEL: dict[str, str] = {
    "INBOX": "INBOX",
    "Sent": "SENT",
    "Drafts": "DRAFT",
    "Trash": "TRASH",
    "Spam": "SPAM",
}

_LABEL_TO_FOLDER: dict[str, str] = {v: k for k, v in _FOLDER_TO_LABEL.items()}


def _folder_to_label(folder: str) -> str:
    """Map a folder name to a Gmail label ID."""
    return _FOLDER_TO_LABEL.get(folder, folder)


def _label_to_folder(label_ids: list[str]) -> str:
    """Map Gmail label IDs to a folder name (best-effort first match)."""
    for label in label_ids:
        if label in _LABEL_TO_FOLDER:
            return _LABEL_TO_FOLDER[label]
    return label_ids[0] if label_ids else "INBOX"


# ── Header / body helpers ──


def _extract_header(headers: list[dict], name: str) -> str:
    """Find a header value by name from a Gmail headers list."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _parse_gmail_address(raw: str) -> EmailAddress:
    """Parse a raw address string like ``"John Doe <john@example.com>"``."""
    if not raw:
        return EmailAddress(address="", name="")
    if "<" in raw and ">" in raw:
        name_part = raw[: raw.index("<")].strip().strip('"')
        addr_part = raw[raw.index("<") + 1 : raw.index(">")].strip()
        return EmailAddress(address=addr_part, name=name_part)
    return EmailAddress(address=raw.strip(), name="")


def _parse_address_list(raw: str) -> list[EmailAddress]:
    """Parse a comma-separated address header into a list."""
    if not raw:
        return []
    # Split on commas, but respect angle brackets
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in raw:
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return [_parse_gmail_address(p) for p in parts if p]


def _decode_body(data: str) -> str:
    """Decode a base64url-encoded body string to UTF-8 text."""
    if not data:
        return ""
    # Gmail uses base64url without padding
    padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _decode_body_bytes(data: str) -> bytes:
    """Decode a base64url-encoded body string to raw bytes."""
    if not data:
        return b""
    padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
    return base64.urlsafe_b64decode(padded)


# ── Outbound (sending) ──


def outbound_to_raw_b64(message: OutboundMessage, default_from_email: str) -> str:
    """
    Build a MIME message from an OutboundMessage DTO and return it
    as a base64url-encoded string suitable for the Gmail API.

    Supports:
    - Plain text and HTML body
    - CC/BCC via ``message.extra``
    - File attachments
    """
    extra = message.extra or {}
    from_email = extra.get("from_email", "") or default_from_email
    cc = extra.get("cc", [])
    bcc = extra.get("bcc", [])

    has_attachments = bool(message.attachments)
    has_both_bodies = bool(message.body) and bool(message.html_body)

    if has_attachments:
        mime_msg = MIMEMultipart("mixed")
        if has_both_bodies:
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(message.body, "plain", "utf-8"))
            alt.attach(MIMEText(message.html_body, "html", "utf-8"))
            mime_msg.attach(alt)
        elif message.html_body:
            mime_msg.attach(MIMEText(message.html_body, "html", "utf-8"))
        elif message.body:
            mime_msg.attach(MIMEText(message.body, "plain", "utf-8"))

        for att in message.attachments:
            content = att.get("content", b"")
            if isinstance(content, str):
                content = content.encode("utf-8")
            filename = att.get("filename", "attachment")
            content_type = att.get("content_type", "application/octet-stream")
            maintype, _, subtype = content_type.partition("/")
            part = MIMEApplication(content, _subtype=subtype or "octet-stream")
            part.add_header("Content-Disposition", "attachment", filename=filename)
            mime_msg.attach(part)
    elif has_both_bodies:
        mime_msg = MIMEMultipart("alternative")
        mime_msg.attach(MIMEText(message.body, "plain", "utf-8"))
        mime_msg.attach(MIMEText(message.html_body, "html", "utf-8"))
    elif message.html_body:
        mime_msg = MIMEText(message.html_body, "html", "utf-8")
    else:
        mime_msg = MIMEText(message.body or "", "plain", "utf-8")

    mime_msg["To"] = message.to
    mime_msg["From"] = from_email
    if message.subject:
        mime_msg["Subject"] = message.subject
    if cc:
        mime_msg["Cc"] = ", ".join(cc)
    if bcc:
        mime_msg["Bcc"] = ", ".join(bcc)

    reply_to = extra.get("reply_to", "")
    if reply_to:
        mime_msg["Reply-To"] = reply_to

    raw_bytes = mime_msg.as_bytes()
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


def gmail_send_to_report(response: dict, message_id: str) -> DeliveryReport:
    """Map a Gmail send response to a DeliveryReport DTO."""
    gmail_id = response.get("id", "")
    return DeliveryReport(
        message_id=message_id,
        status=DeliveryStatus.SENT,
        extra={"gmail_id": gmail_id, "thread_id": response.get("threadId", "")},
    )


# ── Inbound (inbox) ──


def gmail_message_to_summary(msg: dict, folder: str) -> EmailSummary:
    """
    Map a Gmail message (metadata format) to an EmailSummary DTO.

    Expects the message fetched with ``format=metadata`` and
    ``metadataHeaders=From,To,Subject,Date``.
    """
    headers = msg.get("payload", {}).get("headers", [])
    label_ids = msg.get("labelIds", [])

    sender_raw = _extract_header(headers, "From")
    to_raw = _extract_header(headers, "To")
    date_raw = _extract_header(headers, "Date")
    subject = _extract_header(headers, "Subject")

    date = None
    if date_raw:
        try:
            date = parsedate_to_datetime(date_raw)
        except Exception:
            pass

    # Check if any part has a filename (attachment indicator)
    has_attachments = _check_has_attachments(msg.get("payload", {}))

    return EmailSummary(
        message_id=msg["id"],
        folder=folder,
        subject=subject,
        sender=_parse_gmail_address(sender_raw) if sender_raw else None,
        to=_parse_address_list(to_raw),
        date=date,
        snippet=msg.get("snippet", ""),
        is_read="UNREAD" not in label_ids,
        is_flagged="STARRED" in label_ids,
        has_attachments=has_attachments,
    )


def _check_has_attachments(payload: dict) -> bool:
    """Recursively check if any MIME part has a filename (attachment)."""
    if payload.get("filename"):
        return True
    for part in payload.get("parts", []):
        if _check_has_attachments(part):
            return True
    return False


def gmail_message_to_detail(msg: dict, folder: str) -> EmailDetail:
    """
    Map a Gmail message (full format) to an EmailDetail DTO.

    Walks the payload parts tree to extract text/html bodies and
    attachment metadata.
    """
    headers = msg.get("payload", {}).get("headers", [])
    label_ids = msg.get("labelIds", [])
    payload = msg.get("payload", {})

    sender_raw = _extract_header(headers, "From")
    to_raw = _extract_header(headers, "To")
    cc_raw = _extract_header(headers, "Cc")
    bcc_raw = _extract_header(headers, "Bcc")
    date_raw = _extract_header(headers, "Date")
    subject = _extract_header(headers, "Subject")
    in_reply_to = _extract_header(headers, "In-Reply-To")
    references_raw = _extract_header(headers, "References")

    date = None
    if date_raw:
        try:
            date = parsedate_to_datetime(date_raw)
        except Exception:
            pass

    references = references_raw.split() if references_raw else []

    # Walk parts to extract bodies and attachments
    text_body = ""
    html_body = ""
    attachments: list[EmailAttachmentInfo] = []

    _walk_parts(payload, attachments, text_body_out := [], html_body_out := [])
    if text_body_out:
        text_body = text_body_out[0]
    if html_body_out:
        html_body = html_body_out[0]

    # Collect all headers as a dict
    all_headers = {h["name"]: h["value"] for h in headers}

    return EmailDetail(
        message_id=msg["id"],
        folder=folder,
        subject=subject,
        sender=_parse_gmail_address(sender_raw) if sender_raw else None,
        to=_parse_address_list(to_raw),
        cc=_parse_address_list(cc_raw),
        bcc=_parse_address_list(bcc_raw),
        date=date,
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
        is_read="UNREAD" not in label_ids,
        is_flagged="STARRED" in label_ids,
        in_reply_to=in_reply_to,
        references=references,
        headers=all_headers,
    )


def _walk_parts(
    payload: dict,
    attachments: list[EmailAttachmentInfo],
    text_body_out: list[str],
    html_body_out: list[str],
) -> None:
    """
    Recursively walk Gmail payload parts.

    Extracts text/html bodies and attachment metadata. Inline content
    (with ``body.data``) is decoded directly; attachments with
    ``body.attachmentId`` require a separate download call.
    """
    mime_type = payload.get("mimeType", "")
    filename = payload.get("filename", "")
    body = payload.get("body", {})
    parts = payload.get("parts", [])

    if filename:
        # This is an attachment
        attachment_id = body.get("attachmentId", "")
        size = body.get("size", 0)
        attachments.append(
            EmailAttachmentInfo(
                attachment_id=attachment_id,
                filename=filename,
                content_type=mime_type,
                size=size,
            )
        )
        return

    if parts:
        # Multipart — recurse into children
        for part in parts:
            _walk_parts(part, attachments, text_body_out, html_body_out)
        return

    # Leaf part with body data
    data = body.get("data", "")
    if mime_type == "text/plain" and not text_body_out:
        text_body_out.append(_decode_body(data))
    elif mime_type == "text/html" and not html_body_out:
        html_body_out.append(_decode_body(data))


def gmail_attachment_to_content(
    data: dict,
    attachment_id: str,
    filename: str,
    content_type: str,
) -> EmailAttachmentContent:
    """
    Convert Gmail attachment data response to an EmailAttachmentContent DTO.

    Args:
        data: Response from ``messages/{id}/attachments/{attachmentId}``.
        attachment_id: The Gmail attachment ID.
        filename: Original filename from the message payload.
        content_type: MIME type of the attachment.

    Returns:
        EmailAttachmentContent with decoded raw bytes.
    """
    raw_bytes = _decode_body_bytes(data.get("data", ""))
    return EmailAttachmentContent(
        attachment_id=attachment_id,
        filename=filename,
        content_type=content_type,
        size=len(raw_bytes),
        content=raw_bytes,
    )
