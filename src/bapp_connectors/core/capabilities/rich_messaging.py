"""
Rich messaging capability — optional interface for providers that support
attachments, locations, contacts, and other structured content.

Providers like WhatsApp, Telegram, and Facebook Messenger implement this.
Simple providers like GoIP, RoboSMS, and SMTP do not.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import (
        DeliveryReport,
        InboundMessage,
        MessageAttachment,
        MessageContact,
        MessageLocation,
    )


class RichMessagingCapability(ABC):
    """Adapter supports rich message content (media, locations, contacts)."""

    # ── Inbound: extract structured content from received messages ──

    @abstractmethod
    def get_attachments(self, message: InboundMessage) -> list[MessageAttachment]:
        """Extract attachments (images, documents, video, audio) from an inbound message."""
        ...

    @abstractmethod
    def get_location(self, message: InboundMessage) -> MessageLocation | None:
        """Extract a shared location from an inbound message. Returns None if not present."""
        ...

    @abstractmethod
    def get_contacts(self, message: InboundMessage) -> list[MessageContact]:
        """Extract shared contacts from an inbound message."""
        ...

    # ── Outbound: send structured content ──

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
        return self.send(message)  # type: ignore[attr-defined]  # provided by MessagingPort

    def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
        reply_to: str = "",
    ) -> DeliveryReport:
        """Send a location message."""
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
        return self.send(message)  # type: ignore[attr-defined]

    def send_contact(
        self,
        to: str,
        name: str,
        phone: str,
        email: str = "",
        reply_to: str = "",
        **kwargs,
    ) -> DeliveryReport:
        """Send a contact card."""
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
        return self.send(message)  # type: ignore[attr-defined]
