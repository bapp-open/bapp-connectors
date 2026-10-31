"""
Pydantic models for the Graph ``me/accounts`` payload consumed by the Meta provider.

These model raw Graph objects — they are NOT normalized DTOs.
``extra="allow"`` preserves fields we do not model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MetaInstagramAccount(BaseModel):
    """Instagram Business/Creator account linked to a Page (``instagram_business_account`` expansion)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    username: str = ""
    name: str = ""
    profile_picture_url: str = ""


class MetaPage(BaseModel):
    """A Page from ``me/accounts``, with its Page access token and optional linked Instagram account."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    username: str = ""
    picture: dict = {}
    access_token: str = ""
    instagram_business_account: MetaInstagramAccount | None = None
