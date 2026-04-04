"""
SMTP/IMAP mappers — convert raw email.message.Message objects to framework DTOs.
"""

from __future__ import annotations

import hashlib
import logging
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from bapp_connectors.core.dto import (
    EmailAddress,
    EmailAttachmentContent,
    EmailAttachmentInfo,
    EmailDetail,
    EmailSummary,
)
from bapp_connectors.providers.email.smtp.client import _decode_header_value

logger = logging.getLogger(__name__)


def _parse_address(raw: str) -> EmailAddress:
    """Parse a single raw address header into an EmailAddress DTO."""
    name, addr = parseaddr(raw)
    return EmailAddress(
        name=_decode_header_value(name),
        address=addr,
    )


def _parse_address_list(raw: str) -> list[EmailAddress]:
    """Parse a comma-separated address header into a list of EmailAddress DTOs."""
    if not raw:
        return []
    # Split on commas, but respect quoted strings
    from email.utils import getaddresses

    pairs = getaddresses([raw])
    return [
        EmailAddress(name=_decode_header_value(name), address=addr)
        for name, addr in pairs
        if addr
    ]


def _parse_date(msg: Message):
    """Safely parse the Date header."""
    date_str = msg.get("Date", "")
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _make_attachment_id(uid: str, index: int, filename: str) -> str:
    """Deterministic attachment ID from message UID, part index, and filename."""
    raw = f"{uid}:{index}:{filename}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Public mappers ──


def headers_to_summary(
    uid: str,
    msg: Message,
    flags: set[str],
    folder: str,
    *,
    has_attachments: bool = False,
) -> EmailSummary:
    """Map IMAP headers + flags to an EmailSummary DTO."""
    subject = _decode_header_value(msg.get("Subject", ""))
    sender_raw = msg.get("From", "")
    to_raw = msg.get("To", "")

    return EmailSummary(
        message_id=uid,
        folder=folder,
        subject=subject,
        sender=_parse_address(sender_raw) if sender_raw else None,
        to=_parse_address_list(to_raw),
        date=_parse_date(msg),
        snippet=subject[:100],
        is_read="\\Seen" in flags,
        is_flagged="\\Flagged" in flags,
        has_attachments=has_attachments,
    )


def message_to_detail(
    uid: str,
    msg: Message,
    folder: str,
) -> EmailDetail:
    """Map a full RFC822 message to an EmailDetail DTO."""
    subject = _decode_header_value(msg.get("Subject", ""))

    text_body = ""
    html_body = ""
    attachments: list[EmailAttachmentInfo] = []

    for part_index, part in enumerate(msg.walk()):
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition:
            filename = part.get_filename() or f"attachment_{part_index}"
            filename = _decode_header_value(filename)
            payload = part.get_payload(decode=True)
            size = len(payload) if payload else 0
            attachments.append(
                EmailAttachmentInfo(
                    attachment_id=_make_attachment_id(uid, part_index, filename),
                    filename=filename,
                    content_type=content_type,
                    size=size,
                )
            )
        elif content_type == "text/plain" and not text_body:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                text_body = payload.decode(charset, errors="replace")
        elif content_type == "text/html" and not html_body:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

    # Parse flags from the message (not available in RFC822 fetch directly,
    # but the adapter passes them via headers if needed)
    flags_raw = msg.get("X-IMAP-Flags", "")
    flags = set(flags_raw.split()) if flags_raw else set()

    # References header is space-separated message IDs
    references_raw = msg.get("References", "")
    references = references_raw.split() if references_raw else []

    # Collect headers
    headers = {k: _decode_header_value(v) for k, v in msg.items()}

    return EmailDetail(
        message_id=uid,
        folder=folder,
        subject=subject,
        sender=_parse_address(msg.get("From", "")) if msg.get("From") else None,
        to=_parse_address_list(msg.get("To", "")),
        cc=_parse_address_list(msg.get("Cc", "")),
        bcc=_parse_address_list(msg.get("Bcc", "")),
        date=_parse_date(msg),
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
        is_read="\\Seen" in flags,
        is_flagged="\\Flagged" in flags,
        in_reply_to=msg.get("In-Reply-To", ""),
        references=references,
        headers=headers,
    )


def extract_attachment_content(
    uid: str,
    attachment_id: str,
    msg: Message,
) -> EmailAttachmentContent | None:
    """Extract a specific attachment's content from a full message."""
    for part_index, part in enumerate(msg.walk()):
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition:
            filename = part.get_filename() or f"attachment_{part_index}"
            filename = _decode_header_value(filename)
            expected_id = _make_attachment_id(uid, part_index, filename)
            if expected_id == attachment_id:
                payload = part.get_payload(decode=True) or b""
                return EmailAttachmentContent(
                    attachment_id=attachment_id,
                    filename=filename,
                    content_type=part.get_content_type(),
                    size=len(payload),
                    content=payload,
                )
    return None
