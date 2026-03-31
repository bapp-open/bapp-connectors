"""
Matrix Client-Server API client — raw HTTP calls only, no business logic.

Uses the Matrix Client-Server API v3.
Sending uses idempotent PUT with transaction IDs.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class MatrixApiClient:
    """Low-level Matrix Client-Server API client."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _txn_id(self) -> str:
        return uuid.uuid4().hex

    # ── Auth / Connection Test ──

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

    def get_joined_rooms(self) -> dict:
        """GET /joined_rooms"""
        return self.http.call("GET", "joined_rooms")
