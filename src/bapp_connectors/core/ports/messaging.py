"""
Messaging port — the common contract for SMS, email, WhatsApp, etc.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import DeliveryReport, OutboundMessage


class MessagingPort(BasePort):
    """
    Common contract for all messaging adapters (SMS, email, WhatsApp, etc.).
    """

    @abstractmethod
    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single message."""
        ...

    @abstractmethod
    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple messages in bulk."""
        ...
