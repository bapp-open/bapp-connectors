"""Project provisioning capability — list teams, create projects and read their client keys."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import MonitoredProject, MonitoringTeam, ProjectKey


class ProjectProvisioningCapability(ABC):
    """Adapter can create projects on the provider, not just read them.

    Requires credentials with write scope on projects (e.g. Sentry `project:write`).
    `ref` is the provider-side project identifier, as in `MonitoredProject.ref`.
    """

    @abstractmethod
    def list_teams(self) -> list[MonitoringTeam]:
        """List the teams that can own new projects."""
        ...

    @abstractmethod
    def create_project(
        self,
        team: str,
        name: str,
        slug: str | None = None,
        platform: str | None = None,
    ) -> MonitoredProject:
        """Create a project owned by the team with slug `team`.

        `slug` defaults to the provider's choice (derived from `name`);
        `platform` is a provider platform tag, e.g. python | javascript.
        """
        ...

    @abstractmethod
    def list_keys(self, ref: str) -> list[ProjectKey]:
        """List the client keys (DSNs) of project `ref`."""
        ...
