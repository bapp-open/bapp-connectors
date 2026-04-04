"""
Email port — the common contract for email providers (SMTP, SES, Mailchimp, etc.).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import DeliveryReport, OutboundMessage


class EmailPort(BasePort):
    """
    Common contract for all email adapters.

    For inbox reading (fetch, get, download attachment), see InboxCapability.
    """

    @abstractmethod
    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single email."""
        ...

    @abstractmethod
    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple emails in bulk."""
        ...
