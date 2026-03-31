"""
Instagram Messaging API client — raw HTTP calls only, no business logic.

Uses Meta's Graph API. DMs are sent via POST /{ig-user-id}/messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class InstagramApiClient:
    """Low-level Instagram Messaging API client."""

    def __init__(self, http_client: ResilientHttpClient, ig_user_id: str):
        self.http = http_client
        self.ig_user_id = ig_user_id
        self._messages_path = f"{ig_user_id}/messages"

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by fetching Instagram account info."""
        try:
            self.get_account_info()
            return True
        except Exception:
            return False

    def get_account_info(self) -> dict:
        """GET /{ig_user_id} — get Instagram account details."""
        return self.http.call("GET", self.ig_user_id, params={"fields": "id,name,username"})

    # ── Text Messages ──

    def send_text(self, recipient_id: str, text: str) -> dict:
        """Send a text DM."""
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Attachments ──

    def send_attachment(self, recipient_id: str, attachment_type: str, url: str) -> dict:
        """Send an attachment (image, audio, video, file) via URL."""
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": attachment_type,
                    "payload": {"url": url},
                },
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Story Replies ──

    def send_story_reply(self, recipient_id: str, text: str, story_id: str) -> dict:
        """Reply to an Instagram story via DM."""
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "message": {
                "text": text,
                "reply_to": {"story_id": story_id},
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Reactions ──

    def send_reaction(self, recipient_id: str, message_id: str, emoji: str) -> dict:
        """React to a message with an emoji."""
        payload: dict[str, Any] = {
            "recipient": {"id": recipient_id},
            "sender_action": "react",
            "payload": {
                "message_id": message_id,
                "reaction": emoji,
            },
        }
        return self.http.call("POST", self._messages_path, json=payload)

    # ── Generic Template ──

    def send_generic_template(self, recipient_id: str, elements: list[dict]) -> dict:
        """Send a generic template (carousel cards)."""
        payload = {
            "recipient": {"id": recipient_id},
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

    # ── Raw ──

    def send_raw(self, payload: dict) -> dict:
        """Send a raw JSON payload to the messages endpoint."""
        return self.http.call("POST", self._messages_path, json=payload)
