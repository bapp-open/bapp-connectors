"""DevOps port — a code-hosting provider: repositories, issues, merge requests, commits, pipelines."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import Commit, Issue, MergeRequest, PaginatedResult, Pipeline, Repository


class DevOpsPort(BasePort):
    """Read operations every DevOps provider must implement.

    Every repository-scoped call takes `ref`, the provider-side identifier returned in
    `Repository.ref`. Writing issues is an optional capability
    (`IssueManagementCapability`), not a port method: a read-only token is enough here.
    """

    @abstractmethod
    def list_projects(self, search: str | None = None, cursor: str | None = None) -> PaginatedResult[Repository]:
        """Repositories visible to the credentials, optionally filtered by `search`."""
        ...

    @abstractmethod
    def get_project(self, ref: str) -> Repository:
        """A single repository by ref."""
        ...

    @abstractmethod
    def list_issues(
        self, ref: str, state: str = "opened", since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[Issue]:
        """Issues of a repository in `state`, updated after `since` when given."""
        ...

    @abstractmethod
    def get_issue(self, ref: str, number: int) -> Issue:
        """A single issue by its per-project number."""
        ...

    @abstractmethod
    def list_merge_requests(
        self, ref: str, state: str = "opened", since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[MergeRequest]:
        """Merge requests of a repository in `state`, updated after `since` when given."""
        ...

    @abstractmethod
    def list_commits(
        self, ref: str, branch: str | None = None, since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[Commit]:
        """Commits on `branch` (default branch when None), authored after `since` when given."""
        ...

    @abstractmethod
    def list_pipelines(
        self, ref: str, branch: str | None = None, cursor: str | None = None
    ) -> PaginatedResult[Pipeline]:
        """Pipeline runs of a repository, newest first, optionally for one `branch`."""
        ...
