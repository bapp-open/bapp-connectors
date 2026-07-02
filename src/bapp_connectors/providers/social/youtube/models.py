"""
Pydantic models for YouTube Data API v3 response payloads.

These model the raw YouTube API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class YouTubeChannel(BaseModel):
    """YouTube channel resource (channels.list item), as used by the mappers."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    snippet: dict = {}
    statistics: dict = {}
    contentDetails: dict = {}


class YouTubeVideo(BaseModel):
    """YouTube video resource (videos.list item), as used by the mappers."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    snippet: dict = {}
    statistics: dict = {}
    contentDetails: dict = {}
