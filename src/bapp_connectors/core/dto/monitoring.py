"""Monitoring family DTOs — error-tracking projects, issues and project stats."""

from __future__ import annotations

from datetime import datetime

from bapp_connectors.core.dto.base import BaseDTO


class MonitoredProject(BaseDTO):
    """A project on the error-tracking provider."""

    ref: str
    """Provider-side identifier used in every other call (e.g. the project slug)."""
    name: str
    slug: str
    platform: str = ""
    """Provider platform tag, e.g. python | javascript."""
    web_url: str = ""
    is_active: bool = True
    extra: dict = {}


class ErrorIssue(BaseDTO):
    """A grouped error (issue) in a monitored project."""

    ref: str
    """Project ref the issue belongs to."""
    id: str
    """Provider-side issue id, used by `get_issue` and the triage calls."""
    short_id: str
    """Human-readable id, e.g. `AIO-BACKEND-1A2`."""
    title: str
    culprit: str = ""
    level: str = "error"
    """Provider level as-is, e.g. fatal | error | warning | info."""
    status: str = "unresolved"
    """unresolved | resolved | ignored"""
    count: int = 0
    """Number of events in the issue."""
    user_count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    is_unhandled: bool = False
    assigned_to: str = ""
    permalink: str = ""
    extra: dict = {}


class MonitoredProjectStats(BaseDTO):
    """Event totals of a project over `period`."""

    ref: str
    """Project ref the stats belong to."""
    period: str
    """Window the totals cover, e.g. 24h | 14d."""
    events: int = 0
    errors_received: int = 0
    errors_rejected: int = 0
