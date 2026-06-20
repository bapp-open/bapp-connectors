"""
Inbox capability — optional interface for providers that support
reading email from a mailbox.

Providers like SMTP (via IMAP), Microsoft Graph, and Gmail implement this.
The interface is protocol-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import (
        EmailAttachmentContent,
        EmailDetail,
        EmailSummary,
    )


class InboxCapability(ABC):
    """Adapter supports reading email from a mailbox."""

    @abstractmethod
    def fetch_messages(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        folder: str = "INBOX",
        limit: int = 50,
    ) -> list[EmailSummary]:
        """
        Fetch email summaries from a mailbox folder within a time window.

        Args:
            since: Start of the time window (inclusive). None = no lower bound.
            until: End of the time window (inclusive). None = no upper bound.
            folder: Mailbox folder name (e.g. "INBOX", "Sent", "Drafts").
            limit: Maximum number of messages to return.

        Returns:
            List of EmailSummary, newest first.
        """
        ...

    @abstractmethod
    def get_message(self, message_id: str, *, folder: str = "INBOX") -> EmailDetail:
        """
        Fetch the full structure of a single email.

        Args:
            message_id: Provider-specific message identifier
                        (e.g. IMAP UID, Graph message ID).
            folder: Mailbox folder the message lives in.

        Returns:
            EmailDetail with headers, bodies, and attachment metadata
            (without attachment content — use download_attachment for that).
        """
        ...

    @abstractmethod
    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        *,
        folder: str = "INBOX",
    ) -> EmailAttachmentContent:
        """
        Download a single attachment from an email.

        Args:
            message_id: Provider-specific message identifier.
            attachment_id: Attachment identifier from EmailAttachmentInfo.
            folder: Mailbox folder the message lives in.

        Returns:
            EmailAttachmentContent with the raw bytes.
        """
        ...

    @abstractmethod
    def delete_message(self, message_id: str, *, folder: str = "INBOX") -> None:
        """
        Delete a message from the mailbox.

        Semantics are provider-defined (IMAP: flag \\Deleted + expunge;
        Gmail: move to Trash).
        """
        ...

    @abstractmethod
    def move_message(
        self, message_id: str, target_folder: str, *, folder: str = "INBOX"
    ) -> None:
        """Move a message from ``folder`` to ``target_folder``."""
        ...

    @abstractmethod
    def mark_read(
        self, message_id: str, *, read: bool = True, folder: str = "INBOX"
    ) -> None:
        """Mark a message as read (``read=True``) or unread (``read=False``)."""
        ...
