"""DevOps family DTOs — repositories, issues, merge requests, commits, pipelines."""

from __future__ import annotations

from datetime import datetime

from bapp_connectors.core.dto.base import BaseDTO


class Repository(BaseDTO):
    """A project / repository on the code-hosting provider."""

    ref: str
    """Provider-side identifier used in every other call (id or url-encoded path)."""
    name: str
    full_path: str
    """Namespaced path, e.g. `group/subgroup/project`."""
    description: str = ""
    web_url: str = ""
    default_branch: str = ""
    visibility: str = ""
    """private | internal | public"""
    archived: bool = False
    last_activity_at: datetime | None = None
    open_issues_count: int | None = None
    """None when the provider does not report it (e.g. issues disabled)."""
    topics: list[str] = []
    namespace: str = ""
    extra: dict = {}


class Issue(BaseDTO):
    """An issue in a repository. `number` is the per-project number (GitLab iid)."""

    ref: str
    """Repository ref the issue belongs to."""
    number: int
    title: str
    description: str = ""
    state: str = "opened"
    """opened | closed"""
    labels: list[str] = []
    author: str = ""
    assignees: list[str] = []
    web_url: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    extra: dict = {}


class IssueDraft(BaseDTO):
    """Payload for creating or updating an issue."""

    title: str
    description: str = ""
    labels: list[str] = []
    assignee_ids: list[str] = []
    """Provider-side user ids."""


class IssueComment(BaseDTO):
    """A comment (note) on an issue."""

    id: str
    body: str
    author: str = ""
    created_at: datetime | None = None


class MergeRequest(BaseDTO):
    """A merge / pull request. `number` is the per-project number (GitLab iid)."""

    ref: str
    """Repository ref the merge request belongs to."""
    number: int
    title: str
    state: str = "opened"
    """opened | closed | merged | locked"""
    source_branch: str = ""
    target_branch: str = ""
    author: str = ""
    web_url: str = ""
    created_at: datetime | None = None
    merged_at: datetime | None = None


class Commit(BaseDTO):
    """A commit on a branch."""

    ref: str
    """Repository ref the commit belongs to."""
    sha: str
    title: str
    author_name: str = ""
    author_email: str = ""
    authored_at: datetime | None = None
    web_url: str = ""


class Pipeline(BaseDTO):
    """A CI pipeline run."""

    ref: str
    """Repository ref the pipeline belongs to."""
    id: str
    status: str
    """Provider status as-is, e.g. running | success | failed | canceled."""
    branch: str = ""
    sha: str = ""
    web_url: str = ""
    created_at: datetime | None = None
    finished_at: datetime | None = None
