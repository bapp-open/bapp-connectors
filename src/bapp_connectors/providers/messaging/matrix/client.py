"""
Matrix Client-Server API client — raw HTTP calls only, no business logic.

Uses the Matrix Client-Server API v3.
Sending uses idempotent PUT with transaction IDs.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import quote

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

# A room id: '!' + opaque id, with ':server[:port]' (room versions 1-11) or without (v12+).
_ROOM_ID = re.compile(r"![A-Za-z0-9._~+=\-]{1,255}(?::[A-Za-z0-9.\-]{1,253}(?::[0-9]{1,5})?)?")


def _ai_room_id(value: Any) -> str:
    """A room id from an agent, checked and percent-encoded into one path segment."""
    if not isinstance(value, str) or not _ROOM_ID.fullmatch(value) or ".." in value:
        raise ValidationError("room_id must be a Matrix room id such as '!abc:example.org'.")
    return quote(value, safe="")


class MatrixApiClient:
    """Low-level Matrix Client-Server API client."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _txn_id(self) -> str:
        return uuid.uuid4().hex

    # ── Auth / Connection Test ──

    @ai_method("read", "The Matrix account behind the connection: user id and device id.")
    def whoami(self) -> dict:
        """GET /account/whoami — verify access token and get user ID."""
        return self.http.call("GET", "account/whoami")

    def test_auth(self) -> bool:
        try:
            self.whoami()
            return True
        except Exception:
            return False

    # ── Messages ──

    def send_event(self, room_id: str, event_type: str, content: dict, txn_id: str | None = None) -> dict:
        """PUT /rooms/{roomId}/send/{eventType}/{txnId}"""
        txn = txn_id or self._txn_id()
        return self.http.call("PUT", f"rooms/{room_id}/send/{event_type}/{txn}", json=content)

    @ai_method("write", "Send a text message to a Matrix room.")
    def send_message(self, room_id: str, body: str, msgtype: str = "m.text", formatted_body: str = "") -> dict:
        """Send a text or notice message."""
        content: dict[str, Any] = {"msgtype": msgtype, "body": body}
        if formatted_body:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted_body
        return self.send_event(room_id, "m.room.message", content)

    def send_image(self, room_id: str, url: str, body: str = "image", info: dict | None = None) -> dict:
        """Send an image message."""
        content: dict[str, Any] = {"msgtype": "m.image", "body": body, "url": url}
        if info:
            content["info"] = info
        return self.send_event(room_id, "m.room.message", content)

    def send_file(self, room_id: str, url: str, body: str = "file", filename: str = "", info: dict | None = None) -> dict:
        """Send a file message."""
        content: dict[str, Any] = {"msgtype": "m.file", "body": body, "url": url}
        if filename:
            content["filename"] = filename
        if info:
            content["info"] = info
        return self.send_event(room_id, "m.room.message", content)

    def send_audio(self, room_id: str, url: str, body: str = "audio", info: dict | None = None) -> dict:
        """Send an audio message."""
        content: dict[str, Any] = {"msgtype": "m.audio", "body": body, "url": url}
        if info:
            content["info"] = info
        return self.send_event(room_id, "m.room.message", content)

    def send_video(self, room_id: str, url: str, body: str = "video", info: dict | None = None) -> dict:
        """Send a video message."""
        content: dict[str, Any] = {"msgtype": "m.video", "body": body, "url": url}
        if info:
            content["info"] = info
        return self.send_event(room_id, "m.room.message", content)

    def send_location(self, room_id: str, geo_uri: str, body: str = "") -> dict:
        """Send a location message."""
        content: dict[str, Any] = {"msgtype": "m.location", "body": body or geo_uri, "geo_uri": geo_uri}
        return self.send_event(room_id, "m.room.message", content)

    # ── Media ──

    def upload_media(self, data: bytes, content_type: str, filename: str = "") -> dict:
        """POST /media/v3/upload — upload media and get mxc:// URI."""
        # Media endpoint uses a different path prefix
        params = {}
        if filename:
            params["filename"] = filename
        return self.http.call(
            "POST", "../media/v3/upload",
            data=data,
            headers={"Content-Type": content_type},
            params=params,
        )

    # ── Rooms ──

    def join_room(self, room_id_or_alias: str) -> dict:
        """POST /join/{roomIdOrAlias}"""
        return self.http.call("POST", f"join/{room_id_or_alias}", json={})

    @ai_method("read", "The ids of the Matrix rooms the account has joined.")
    def get_joined_rooms(self) -> dict:
        """GET /joined_rooms"""
        return self.http.call("GET", "joined_rooms")

    @ai_method(
        "read",
        "Message history of a Matrix room the account has joined (GET /rooms/{id}/messages, no sync, "
        "no read receipt). dir 'b' = newest first. Page with the 'end' token of the previous answer as from_token.",
    )
    def get_room_messages(
        self,
        room_id: str,
        limit: int = 50,
        direction: Literal["b", "f"] = "b",
        from_token: Annotated[str, "free_text"] | None = None,
    ) -> dict:
        """GET /rooms/{roomId}/messages — paginate a joined room's timeline without touching sync state."""
        encoded = _ai_room_id(room_id)
        joined = (self.get_joined_rooms() or {}).get("joined_rooms") or []
        if room_id not in joined:
            raise ValidationError("room_id is not a room the connected Matrix account has joined.")
        params: dict[str, Any] = {"dir": direction, "limit": max(1, min(int(limit), 100))}
        if from_token:
            params["from"] = from_token
        return self.http.call("GET", f"rooms/{encoded}/messages", params=params)
