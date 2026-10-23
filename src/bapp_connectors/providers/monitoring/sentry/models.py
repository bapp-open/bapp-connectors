"""Pydantic models for raw Sentry REST payloads. These are NOT DTOs.

Only the fields the mappers read are declared, under Sentry's own camelCase names;
everything else is kept via `extra="allow"`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _SentryModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class SentryProject(_SentryModel):
    id: str
    slug: str
    name: str = ""
    platform: str | None = None
    status: str | None = None
    isMember: bool | None = None
    dateCreated: str | None = None


class SentryAssignee(_SentryModel):
    id: str | None = None
    type: str | None = None
    """user | team"""
    name: str = ""
    email: str | None = None


class SentryIssue(_SentryModel):
    id: str
    shortId: str = ""
    title: str = ""
    culprit: str | None = None
    level: str = "error"
    status: str = "unresolved"
    count: str | int = 0
    """Sentry sends the event count as a string."""
    userCount: int = 0
    firstSeen: str | None = None
    lastSeen: str | None = None
    isUnhandled: bool = False
    permalink: str = ""
    assignedTo: SentryAssignee | None = None
    project: SentryProject | None = None
    type: str | None = None
    metadata: dict = {}
    logger: str | None = None
    platform: str | None = None
