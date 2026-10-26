"""Issue management capability — create, edit, close and comment on issues."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Issue, IssueComment, IssueDraft


class IssueManagementCapability(ABC):
    """Adapter can write issues, not just read them.

    Requires credentials with write scope on the repository. `number` is the
    per-project issue number, as in `Issue.number`.
    """

    @abstractmethod
    def create_issue(self, ref: str, draft: IssueDraft) -> Issue:
        """Open a new issue in repository `ref`."""
        ...

    @abstractmethod
    def update_issue(self, ref: str, number: int, draft: IssueDraft) -> Issue:
        """Replace title, description, labels and assignees of an existing issue."""
        ...

    @abstractmethod
    def close_issue(self, ref: str, number: int) -> Issue:
        """Close an issue."""
        ...

    @abstractmethod
    def reopen_issue(self, ref: str, number: int) -> Issue:
        """Reopen a closed issue."""
        ...

    @abstractmethod
    def add_issue_comment(self, ref: str, number: int, body: str) -> IssueComment:
        """Add a comment to an issue."""
        ...
