"""
Facebook Messenger Send API client — raw HTTP calls only, no business logic.

Uses Meta's Graph API. Messages are sent via POST /{page_id}/messages.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.social.facebook.client import scrub_graph_paging

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

# Fixed field lists for the agent's reads: none reaches a token.
AI_CONVERSATION_FIELDS = "id,updated_time,message_count,unread_count,participants"
AI_MESSAGE_FIELDS = "id,created_time,from,to,message"
AI_PROFILE_FIELDS = "first_name,last_name"

_PSID = re.compile(r"[0-9]{1,32}")
_CONVERSATION_ID = re.compile(r"t_[A-Za-z0-9_\-]{1,128}")


def _ai_match(pattern: re.Pattern, value: Any, what: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValidationError(f"{what} has an invalid format.")
    return value


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

    @ai_method("read", "The connected Facebook Page: id and name.")
    def get_page_info(self) -> dict:
        """GET /{page_id} — get page details."""
        return self.http.call("GET", self.page_id, params={"fields": "id,name"})

    # ── Text Messages ──

    @ai_method("write", "Send a Messenger text reply to a user (PSID) who messaged the Page.")
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

    # ── Read-only views for an AI agent (fixed fields, connected Page only) ──

    @ai_method(
        "read",
        "The connected Page's Messenger conversations, most recent first: participants, message and unread "
        "counts. Paginate with the 'after' cursor from paging.cursors. Reading marks nothing as seen.",
    )
    def list_conversations(self, limit: int = 25, after: Annotated[str, "free_text"] | None = None) -> dict:
        """GET /{page_id}/conversations with fixed fields."""
        params: dict[str, Any] = {"fields": AI_CONVERSATION_FIELDS, "limit": max(1, min(int(limit), 100))}
        if after:
            params["after"] = after
        return scrub_graph_paging(self.http.call("GET", f"{self.page_id}/conversations", params=params))

    @ai_method(
        "read",
        "Messages of one Page conversation (id 't_...'), newest first. "
        "Paginate with the 'after' cursor from paging.cursors.",
    )
    def get_conversation_messages(
        self, conversation_id: str, limit: int = 25, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        """GET /{conversation_id}/messages with fixed fields."""
        conversation_id = _ai_match(_CONVERSATION_ID, conversation_id, "conversation_id")
        self._ai_own_conversation(conversation_id)
        params: dict[str, Any] = {"fields": AI_MESSAGE_FIELDS, "limit": max(1, min(int(limit), 100))}
        if after:
            params["after"] = after
        return scrub_graph_paging(self.http.call("GET", f"{conversation_id}/messages", params=params))

    def _ai_own_conversation(self, conversation_id: str) -> None:
        """Refuse a thread the connected Page is not a participant of (a multi-Page token sees others)."""
        info = self.http.call("GET", conversation_id, params={"fields": "participants"}) or {}
        participants = (info.get("participants") or {}).get("data") or [] if isinstance(info, dict) else []
        if not any(isinstance(p, dict) and str(p.get("id", "")) == str(self.page_id) for p in participants):
            raise ValidationError(f"Conversation {conversation_id} does not belong to the connected Page.")

    @ai_method("read", "First and last name of a user (page-scoped id, PSID) who messaged the Page.")
    def get_customer_profile(self, psid: str) -> dict:
        """GET /{psid} with fixed fields."""
        return self.http.call("GET", _ai_match(_PSID, psid, "psid"), params={"fields": AI_PROFILE_FIELDS})

    # ── Raw ──

    def send_raw(self, payload: dict) -> dict:
        """Send a raw JSON payload to the messages endpoint."""
        return self.http.call("POST", self._messages_path, json=payload)
