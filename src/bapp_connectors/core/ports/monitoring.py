"""Monitoring port — an error-tracking provider: projects, issues and project stats."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ErrorIssue, MonitoredProject, MonitoredProjectStats, PaginatedResult


class MonitoringPort(BasePort):
    """Read operations every monitoring provider must implement.

    Every project-scoped call takes `ref`, the provider-side identifier returned in
    `MonitoredProject.ref`. Changing an issue's state is an optional capability
    (`IssueTriageCapability`), not a port method: a read-only token is enough here.
    """

    @abstractmethod
    def list_projects(self, cursor: str | None = None) -> PaginatedResult[MonitoredProject]:
        """Projects visible to the credentials."""
        ...

    @abstractmethod
    def get_project(self, ref: str) -> MonitoredProject:
        """A single project by ref."""
        ...

    @abstractmethod
    def list_issues(
        self,
        ref: str,
        query: str = "is:unresolved",
        period: str = "14d",
        sort: str = "date",
        cursor: str | None = None,
    ) -> PaginatedResult[ErrorIssue]:
        """Issues of a project matching the provider search `query`, seen within `period`, ordered by `sort`."""
        ...

    @abstractmethod
    def get_issue(self, issue_id: str) -> ErrorIssue:
        """A single issue by its provider-side id."""
        ...

    @abstractmethod
    def get_project_stats(self, ref: str, period: str = "24h") -> MonitoredProjectStats:
        """Event totals of a project over `period`."""
        ...
