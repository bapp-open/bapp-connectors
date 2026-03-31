"""
Messaging port — the common contract for SMS, email, WhatsApp, etc.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import DeliveryReport, InboundMessage, OutboundMessage


class MessagingPort(BasePort):
    """
    Common contract for all messaging adapters (SMS, email, WhatsApp, etc.).

    For rich content (attachments, locations, contacts), see RichMessagingCapability.
    """

    @abstractmethod
    def send(self, message: OutboundMessage) -> DeliveryReport:
        """Send a single message."""
        ...

    @abstractmethod
    def send_bulk(self, messages: list[OutboundMessage]) -> list[DeliveryReport]:
        """Send multiple messages in bulk."""
        ...

    def reply(self, inbound: InboundMessage, body: str, **kwargs) -> DeliveryReport:
        """
        Reply to an inbound message.

        Builds an OutboundMessage addressed to the inbound sender with reply_to
        set to the inbound message ID, then delegates to send().

        Override in subclasses for provider-specific reply behavior.
        """
        from bapp_connectors.core.dto import OutboundMessage

        message = OutboundMessage(
            channel=inbound.channel,
            to=inbound.sender,
            reply_to=inbound.message_id,
            body=body,
            extra=kwargs,
        )
        return self.send(message)
