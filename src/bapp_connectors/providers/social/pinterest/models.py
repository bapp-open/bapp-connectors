"""
Pydantic models for Pinterest API v5 response payloads.

These model the raw Pinterest API — they are NOT normalized DTOs.
``extra="allow"`` preserves fields we do not model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PinterestUserAccount(BaseModel):
    """Pinterest user object from user_account."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    username: str = ""
    profile_image: str = ""
    about: str = ""
    follower_count: int | None = None
    following_count: int | None = None
    monthly_views: int | None = None
    pin_count: int | None = None


class PinterestMedia(BaseModel):
    """Pin media object (``media_type`` + rendered ``images`` by size)."""

    model_config = ConfigDict(extra="allow")

    media_type: str = ""
    images: dict = {}


class PinterestPin(BaseModel):
    """Pinterest pin object from pins and pins/{id}.

    Pinterest returns ``null`` for unset text fields — they are modelled as
    ``str | None`` and coerced to ``""`` in the mappers.
    """

    model_config = ConfigDict(extra="allow")

    id: str = ""
    created_at: str | None = None
    link: str | None = None
    title: str | None = None
    description: str | None = None
    board_id: str | None = None
    media: PinterestMedia | None = None
