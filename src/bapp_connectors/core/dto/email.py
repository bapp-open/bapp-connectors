"""
Normalized DTOs for email inbox operations (fetch, read, download).

These DTOs are provider-agnostic — usable by IMAP, Microsoft Graph, Gmail API, etc.
"""

from __future__ import annotations

from datetime import datetime

from .base import BaseDTO


class EmailAddress(BaseDTO):
    """Parsed email address with optional display name."""

    address: str
    name: str = ""


class EmailAttachmentInfo(BaseDTO):
    """Attachment metadata returned as part of an email detail."""

    attachment_id: str
    filename: str = ""
    content_type: str = "application/octet-stream"
    size: int | None = None


class EmailAttachmentContent(BaseDTO):
    """Full attachment content returned by download_attachment."""

    attachment_id: str
    filename: str = ""
    content_type: str = "application/octet-stream"
    size: int | None = None
    content: bytes = b""


class EmailSummary(BaseDTO):
    """Lightweight email summary returned by fetch_messages."""

    message_id: str
    folder: str = "INBOX"
    subject: str = ""
    sender: EmailAddress | None = None
    to: list[EmailAddress] = []
    date: datetime | None = None
    snippet: str = ""
    is_read: bool = False
    is_flagged: bool = False
    has_attachments: bool = False


class EmailDetail(BaseDTO):
    """Full email structure returned by get_message."""

    message_id: str
    folder: str = "INBOX"
    subject: str = ""
    sender: EmailAddress | None = None
    to: list[EmailAddress] = []
    cc: list[EmailAddress] = []
    bcc: list[EmailAddress] = []
    date: datetime | None = None
    text_body: str = ""
    html_body: str = ""
    attachments: list[EmailAttachmentInfo] = []
    is_read: bool = False
    is_flagged: bool = False
    in_reply_to: str = ""
    references: list[str] = []
    headers: dict[str, str] = {}
