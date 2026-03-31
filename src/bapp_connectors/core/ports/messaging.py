"""
Messaging port — the common contract for SMS, email, WhatsApp, etc.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import (
        DeliveryReport,
        InboundMessage,
        MessageAttachment,
        MessageContact,
        MessageLocation,
        OutboundMessage,
    )


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

    def send_media(
        self,
        to: str,
        media_type: str,
        media_url: str = "",
        media_id: str = "",
        caption: str = "",
        filename: str = "",
        reply_to: str = "",
        **kwargs,
    ) -> DeliveryReport:
        """Send a media message (image, document, video, audio, sticker).

        Builds an OutboundMessage with the right extra fields and delegates to send().
        Providers that support media will handle this via their payload builders.

        Args:
            to: Recipient identifier.
            media_type: One of "image", "document", "video", "audio", "voice", "sticker".
            media_url: Public URL of the media (use this or media_id).
            media_id: Provider-specific media ID (use this or media_url).
            caption: Optional caption text.
            filename: Optional filename (for documents).
            reply_to: Optional message ID to reply to.
        """
        from bapp_connectors.core.dto import MessageChannel, OutboundMessage

        message = OutboundMessage(
            channel=MessageChannel.OTHER,
            to=to,
            body=caption,
            reply_to=reply_to,
            extra={
                "media_type": media_type,
                "media_url": media_url,
                "media_id": media_id,
                "caption": caption,
                "filename": filename,
                **kwargs,
            },
        )
        return self.send(message)

    def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
        reply_to: str = "",
    ) -> DeliveryReport:
        """Send a location message.

        Builds an OutboundMessage with location data and delegates to send().
        Providers must handle ``extra.location`` in their payload builders.
        """
        from bapp_connectors.core.dto import MessageChannel, OutboundMessage

        message = OutboundMessage(
            channel=MessageChannel.OTHER,
            to=to,
            reply_to=reply_to,
            extra={
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "name": name,
                    "address": address,
                },
            },
        )
        return self.send(message)

    def send_contact(
        self,
        to: str,
        name: str,
        phone: str,
        email: str = "",
        reply_to: str = "",
        **kwargs,
    ) -> DeliveryReport:
        """Send a contact card.

        Builds an OutboundMessage with contact data and delegates to send().
        Providers must handle ``extra.contact`` in their payload builders.
        """
        from bapp_connectors.core.dto import MessageChannel, OutboundMessage

        message = OutboundMessage(
            channel=MessageChannel.OTHER,
            to=to,
            reply_to=reply_to,
            extra={
                "contact": {
                    "name": name,
                    "phone": phone,
                    "email": email,
                    **kwargs,
                },
            },
        )
        return self.send(message)

    def get_attachments(self, message: InboundMessage) -> list[MessageAttachment]:
        """Extract attachments (images, documents, video, audio) from an inbound message.

        Override in subclasses to parse provider-specific raw message data.
        Returns an empty list for providers that don't support attachments.
        """
        return []

    def get_location(self, message: InboundMessage) -> MessageLocation | None:
        """Extract a shared location from an inbound message.

        Override in subclasses to parse provider-specific raw message data.
        Returns None if the message doesn't contain a location.
        """
        return None

    def get_contacts(self, message: InboundMessage) -> list[MessageContact]:
        """Extract shared contacts from an inbound message.

        Override in subclasses to parse provider-specific raw message data.
        Returns an empty list for providers that don't support contact sharing.
        """
        return []
