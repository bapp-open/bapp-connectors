"""Mailbox capability — manage email accounts on a hosting plan."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Mailbox


class MailboxCapability(ABC):
    """Adapter can list and manage the account's email boxes.

    Quotas are expressed in megabytes because that is what every panel's UI uses;
    the `Mailbox` DTO reports usage in bytes. `None` means unlimited on both sides.
    """

    @abstractmethod
    def list_mailboxes(self, domain: str | None = None) -> list[Mailbox]:
        """Every mailbox, optionally restricted to one domain."""
        ...

    @abstractmethod
    def create_mailbox(self, email: str, password: str, quota_mb: int | None = None) -> Mailbox:
        """Create a mailbox and return it as re-read from the provider."""
        ...

    @abstractmethod
    def delete_mailbox(self, email: str) -> bool:
        """Delete a mailbox. Returns True when the provider confirms."""
        ...

    @abstractmethod
    def set_mailbox_quota(self, email: str, quota_mb: int | None) -> Mailbox:
        """Change a mailbox quota; `None` sets unlimited."""
        ...

    @abstractmethod
    def set_mailbox_password(self, email: str, password: str) -> bool:
        """Change a mailbox password. Providers may reject weak passwords."""
        ...
