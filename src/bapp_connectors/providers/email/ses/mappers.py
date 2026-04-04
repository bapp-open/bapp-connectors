"""
SES mappers — convert OutboundMessage DTOs to SES API kwargs and responses to DTOs.
"""

from __future__ import annotations

from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from typing import Any

from bapp_connectors.core.dto import DeliveryReport, DeliveryStatus, OutboundMessage


def _build_from_address(message: OutboundMessage, default_from_email: str) -> str:
    """Build the From address, optionally with a display name."""
    from_email = message.extra.get("from_email", "") or default_from_email
    from_name = message.extra.get("from_name", "")
    if from_name:
        return formataddr((from_name, from_email))
    return from_email


def outbound_to_ses_kwargs(
    message: OutboundMessage,
    default_from_email: str,
) -> dict[str, Any]:
    """
    Build kwargs for SES v2 send_simple_email from an OutboundMessage.

    Used when the message has no attachments (simple send path).
    """
    from_address = _build_from_address(message, default_from_email)

    kwargs: dict[str, Any] = {
        "from_email": from_address,
        "to": [message.to],
        "subject": message.subject,
        "body_text": message.body,
        "body_html": message.html_body,
    }

    cc = message.extra.get("cc")
    if cc:
        kwargs["cc"] = cc if isinstance(cc, list) else [cc]

    bcc = message.extra.get("bcc")
    if bcc:
        kwargs["bcc"] = bcc if isinstance(bcc, list) else [bcc]

    reply_to = message.extra.get("reply_to")
    if reply_to:
        kwargs["reply_to"] = reply_to if isinstance(reply_to, list) else [reply_to]

    return kwargs


def outbound_to_raw_mime(
    message: OutboundMessage,
    default_from_email: str,
) -> bytes:
    """
    Build raw MIME message bytes from an OutboundMessage.

    Used when the message has attachments (raw send path).
    Uses Python's email.mime modules.
    """
    from_address = _build_from_address(message, default_from_email)

    msg = MIMEMultipart("mixed")
    msg["Subject"] = message.subject
    msg["From"] = from_address
    msg["To"] = message.to
    msg["Date"] = formatdate(localtime=True)

    cc = message.extra.get("cc")
    if cc:
        cc_list = cc if isinstance(cc, list) else [cc]
        msg["Cc"] = ", ".join(cc_list)

    reply_to = message.extra.get("reply_to")
    if reply_to:
        reply_list = reply_to if isinstance(reply_to, list) else [reply_to]
        msg["Reply-To"] = ", ".join(reply_list)

    # Build the body as an alternative part
    body_part = MIMEMultipart("alternative")
    if message.body:
        body_part.attach(MIMEText(message.body, "plain", "utf-8"))
    if message.html_body:
        body_part.attach(MIMEText(message.html_body, "html", "utf-8"))
    if not message.body and not message.html_body:
        body_part.attach(MIMEText("", "plain", "utf-8"))
    msg.attach(body_part)

    # Add attachments
    for att in message.attachments:
        content_type = att.get("content_type", "application/octet-stream")
        maintype, _, subtype = content_type.partition("/")
        part = MIMEBase(maintype or "application", subtype or "octet-stream")
        part.set_payload(att.get("content", b""))
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=att.get("filename", "attachment"),
        )
        msg.attach(part)

    return msg.as_bytes()


def ses_response_to_report(
    response: dict[str, Any],
    message_id: str,
) -> DeliveryReport:
    """
    Map an SES SendEmail response to a DeliveryReport DTO.

    SES is asynchronous — a successful send_email call means the message
    is queued, not yet delivered.
    """
    ses_message_id = response.get("MessageId", "")
    return DeliveryReport(
        message_id=message_id,
        status=DeliveryStatus.QUEUED,
        extra={"ses_message_id": ses_message_id} if ses_message_id else {},
    )
