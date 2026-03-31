"""
Facebook Messenger Send API client — raw HTTP calls only, no business logic.

Uses Meta's Graph API. Messages are sent via POST /{page_id}/messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class MessengerApiClient:
    """Low-level Facebook Messenger Send API client."""

    def __init__(self, http_client: ResilientHttpClient, page_id: str):
        self.http = http_client
        self.page_id = page_id
        self._messages_path = f"{page_id}/messages"

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by fetching page info."""
        try:
            self.http.call("GET", self.page_id, params={"fields": "id,name"})
            return True
        except Exception:
            return False

    def get_page_info(self) -> dict:
        """GET /{page_id} — get page details."""
        return self.http.call("GET", self.page_id, params={"fields": "id,name"})

    # ── Text Messages ──

    def send_text(self, recipient_id: str, text: str) -> dict:
        """Send a text message."""
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {"text": text},
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Attachments ──

    def send_attachment(
        self,
        recipient_id: str,
        attachment_type: str,
        url: str,
        is_reusable: bool = True,
    ) -> dict:
        """Send an attachment (image, audio, video, file) via URL."""
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": attachment_type,
                    "payload": {
                        "url": url,
                        "is_reusable": is_reusable,
                    },
                },
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def send_attachment_by_id(self, recipient_id: str, attachment_type: str, attachment_id: str) -> dict:
        """Send a previously uploaded attachment by ID."""
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": attachment_type,
                    "payload": {"attachment_id": attachment_id},
                },
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Templates ──

    def send_generic_template(self, recipient_id: str, elements: list[dict]) -> dict:
        """Send a generic template (cards/carousel)."""
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": elements,
                    },
                },
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    def send_button_template(self, recipient_id: str, text: str, buttons: list[dict]) -> dict:
        """Send a button template."""
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text,
                        "buttons": buttons,
                    },
                },
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Quick Replies ──

    def send_quick_replies(self, recipient_id: str, text: str, quick_replies: list[dict]) -> dict:
        """Send a message with quick reply buttons."""
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {
                "text": text,
                "quick_replies": quick_replies,
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Sender Actions ──

    def send_action(self, recipient_id: str, action: str) -> dict:
        """Send a sender action (typing_on, typing_off, mark_seen)."""
        payload = {
            "recipient": {"id": recipient_id},
            "sender_action": action,
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── User Profile ──

    def get_user_profile(self, psid: str, fields: str = "first_name,last_name,profile_pic") -> dict:
        """GET /{psid} — get user profile info."""
        return self.http.call("GET", psid, params={"fields": fields})

    # ── Raw ──

    def send_raw(self, payload: dict) -> dict:
        """Send a raw JSON payload to the messages endpoint."""
        return self.http.call("POST", self._messages_path, json=payload)
