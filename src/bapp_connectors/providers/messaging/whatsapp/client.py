"""
WhatsApp Cloud API client — raw HTTP calls only, no business logic.

Uses Meta's Graph API with Bearer token authentication.
All messages are sent via POST /{phone_number_id}/messages.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class WhatsAppApiClient:
    """
    Low-level WhatsApp Cloud API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        phone_number_id: str,
    ):
        self.http = http_client
        self.phone_number_id = phone_number_id
        self._messages_path = f"{phone_number_id}/messages"
        self._media_path = f"{phone_number_id}/media"

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by fetching phone number details."""
        try:
            self.http.call("GET", self.phone_number_id)
            return True
        except Exception:
            return False

    # ── Text Messages ──

    def send_text(self, to: str, body: str, preview_url: bool = True) -> dict:
        """Send a text message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": preview_url, "body": body},
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def reply_text(self, to: str, body: str, message_id: str, preview_url: bool = True) -> dict:
        """Reply to a specific message with text."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "context": {"message_id": message_id},
            "text": {"preview_url": preview_url, "body": body},
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Template Messages ──

    def send_template(self, to: str, template_name: str, language: str = "en_US", components: list | None = None) -> dict:
        """Send a pre-approved template message."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        if components:
            payload["template"]["components"] = components
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Media Messages ──

    def send_image(self, to: str, image: str, caption: str = "", is_media_id: bool = False) -> dict:
        """Send an image message via URL or media ID."""
        image_data: dict[str, Any] = {"id": image} if is_media_id else {"link": image}
        if caption:
            image_data["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "image",
            "image": image_data,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def send_document(self, to: str, document: str, caption: str = "", filename: str = "", is_media_id: bool = False) -> dict:
        """Send a document message via URL or media ID."""
        doc_data: dict[str, Any] = {"id": document} if is_media_id else {"link": document}
        if caption:
            doc_data["caption"] = caption
        if filename:
            doc_data["filename"] = filename
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "document",
            "document": doc_data,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def send_video(self, to: str, video: str, caption: str = "", is_media_id: bool = False) -> dict:
        """Send a video message via URL or media ID."""
        video_data: dict[str, Any] = {"id": video} if is_media_id else {"link": video}
        if caption:
            video_data["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "video",
            "video": video_data,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def send_audio(self, to: str, audio: str, is_media_id: bool = False) -> dict:
        """Send an audio message via URL or media ID."""
        audio_data: dict[str, Any] = {"id": audio} if is_media_id else {"link": audio}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": audio_data,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def send_sticker(self, to: str, sticker: str, is_media_id: bool = False) -> dict:
        """Send a sticker message via URL or media ID."""
        sticker_data: dict[str, Any] = {"id": sticker} if is_media_id else {"link": sticker}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "sticker",
            "sticker": sticker_data,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Location ──

    def send_location(self, to: str, latitude: str, longitude: str, name: str = "", address: str = "") -> dict:
        """Send a location message."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "location",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "name": name,
                "address": address,
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Interactive Messages ──

    def send_interactive(self, to: str, interactive: dict) -> dict:
        """Send an interactive message (buttons, list, etc.)."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Contacts ──

    def send_contacts(self, to: str, contacts: list[dict]) -> dict:
        """Send contact cards."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "contacts",
            "contacts": contacts,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Reactions ──

    def send_reaction(self, to: str, message_id: str, emoji: str) -> dict:
        """Send an emoji reaction to a message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "reaction",
            "reaction": {"message_id": message_id, "emoji": emoji},
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Message Status ──

    def mark_as_read(self, message_id: str) -> dict:
        """Mark a message as read."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Media Management ──

    def get_media_url(self, media_id: str) -> dict:
        """GET /{media_id} — get the download URL for a media object."""
        return self.http.call("GET", media_id)

    def delete_media(self, media_id: str) -> dict:
        """DELETE /{media_id} — delete a media object."""
        return self.http.call("DELETE", media_id, direct_response=False)

    # ── Raw ──

    def send_raw(self, payload: dict) -> dict:
        """Send a raw JSON payload to the messages endpoint."""
        return self.http.call("POST", self._messages_path, json=payload)
