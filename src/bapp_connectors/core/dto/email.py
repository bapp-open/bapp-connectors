"""
Normalized DTOs for email inbox operations (fetch, read, download).

These DTOs are provider-agnostic — usable by IMAP, Microsoft Graph, Gmail API, etc.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

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


class InboxActionType(StrEnum):
    """Termination action a receiver may request for a fetched email."""

    NONE = "none"
    DELETE = "delete"
    MOVE = "move"
    MARK_READ = "mark_read"


class InboxAction(BaseDTO):
    """Instruction returned by an email_received receiver.

    Maps 1:1 to InboxCapability operations. Use the factory classmethods
    rather than constructing directly.
    """

    type: InboxActionType = InboxActionType.NONE
    folder: str = ""      # target folder for MOVE
    read: bool = True     # desired read state for MARK_READ

    @classmethod
    def delete(cls) -> InboxAction:
        return cls(type=InboxActionType.DELETE)

    @classmethod
    def move(cls, folder: str) -> InboxAction:
        return cls(type=InboxActionType.MOVE, folder=folder)

    @classmethod
    def mark_read(cls, read: bool = True) -> InboxAction:
        return cls(type=InboxActionType.MARK_READ, read=read)

    @classmethod
    def none(cls) -> InboxAction:
        return cls(type=InboxActionType.NONE)
