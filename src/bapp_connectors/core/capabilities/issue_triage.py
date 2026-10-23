"""Issue triage capability — resolve, reopen, ignore and assign error issues."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import ErrorIssue


class IssueTriageCapability(ABC):
    """Adapter can change the state of error issues, not just read them.

    Requires credentials with write scope on the project. `issue_id` is the
    provider-side id, as in `ErrorIssue.id`.
    """

    @abstractmethod
    def resolve_issue(self, issue_id: str) -> ErrorIssue:
        """Mark an issue as resolved."""
        ...

    @abstractmethod
    def unresolve_issue(self, issue_id: str) -> ErrorIssue:
        """Reopen a resolved or ignored issue."""
        ...

    @abstractmethod
    def ignore_issue(self, issue_id: str, until: datetime | None = None) -> ErrorIssue:
        """Ignore an issue, indefinitely or until `until` when given."""
        ...

    @abstractmethod
    def assign_issue(self, issue_id: str, email: str) -> ErrorIssue:
        """Assign an issue to the provider user with `email`."""
        ...
