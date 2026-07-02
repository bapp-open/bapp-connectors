"""
Pydantic models for LinkedIn REST API response payloads.

These model the raw LinkedIn objects as consumed by the mappers — they are
NOT normalized DTOs. Field names match LinkedIn's camelCase API fields.
``extra="allow"`` preserves fields we do not model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LinkedInOrganization(BaseModel):
    """Raw organization object (``organizations/{id}``)."""

    model_config = ConfigDict(extra="allow")

    id: int | str = ""
    vanityName: str = ""
    localizedName: str = ""
    localizedDescription: str = ""


class LinkedInPost(BaseModel):
    """Raw post object (``posts`` finder / ``posts/{urn}``)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    author: str = ""
    commentary: str = ""
    createdAt: int | None = None  # epoch milliseconds
    content: dict | None = None
    visibility: str = ""
    lifecycleState: str = ""


class LinkedInShareStatistics(BaseModel):
    """Raw share statistics element (``organizationalEntityShareStatistics``)."""

    model_config = ConfigDict(extra="allow")

    totalShareStatistics: dict = {}
    organizationalEntity: str = ""
    share: str = ""
