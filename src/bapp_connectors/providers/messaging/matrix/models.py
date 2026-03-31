"""
Pydantic models for Matrix Client-Server API request/response payloads.

These model the raw Matrix API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel

# ── Response models ──


class MatrixEventResponse(BaseModel):
    """Response from sending a room event."""

    event_id: str = ""


class MatrixMediaResponse(BaseModel):
    """Response from media upload."""

    content_uri: str = ""


class MatrixWhoamiResponse(BaseModel):
    """Response from /_matrix/client/v3/account/whoami."""

    user_id: str = ""
    device_id: str = ""


# ── Webhook / Appservice models ──


class MatrixEvent(BaseModel):
    """A Matrix room event (from sync or appservice push)."""

    type: str = ""
    event_id: str = ""
    room_id: str = ""
    sender: str = ""
    origin_server_ts: int = 0
    content: dict = {}


class MatrixAppserviceTransaction(BaseModel):
    """Appservice transaction pushed by the homeserver."""

    events: list[dict] = []
