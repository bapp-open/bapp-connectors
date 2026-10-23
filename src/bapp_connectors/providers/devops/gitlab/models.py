"""Pydantic models for raw GitLab REST payloads. These are NOT DTOs.

Only the fields the mappers read are declared; everything else is kept via `extra="allow"`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _GitLabModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class GitLabUser(_GitLabModel):
    id: int
    username: str = ""
    name: str = ""
    email: str | None = None
    avatar_url: str | None = None
    web_url: str | None = None


class GitLabNamespace(_GitLabModel):
    id: int | None = None
    name: str = ""
    path: str = ""
    full_path: str = ""
    kind: str = ""


class GitLabProject(_GitLabModel):
    id: int
    name: str = ""
    path: str = ""
    path_with_namespace: str = ""
    name_with_namespace: str = ""
    description: str | None = None
    web_url: str = ""
    default_branch: str | None = None
    archived: bool = False
    visibility: str | None = None
    created_at: str | None = None
    last_activity_at: str | None = None
    namespace: GitLabNamespace | None = None


class GitLabIssue(_GitLabModel):
    id: int
    iid: int
    project_id: int
    title: str = ""
    description: str | None = None
    state: str = ""
    labels: list[str] = []
    author: GitLabUser | None = None
    assignees: list[GitLabUser] = []
    web_url: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None
    due_date: str | None = None


class GitLabMergeRequest(_GitLabModel):
    id: int
    iid: int
    project_id: int
    title: str = ""
    description: str | None = None
    state: str = ""
    source_branch: str = ""
    target_branch: str = ""
    labels: list[str] = []
    author: GitLabUser | None = None
    draft: bool = False
    web_url: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    merged_at: str | None = None
    closed_at: str | None = None


class GitLabCommit(_GitLabModel):
    id: str
    short_id: str = ""
    title: str = ""
    message: str = ""
    author_name: str = ""
    author_email: str = ""
    authored_date: str | None = None
    committed_date: str | None = None
    web_url: str = ""


class GitLabPipeline(_GitLabModel):
    id: int
    iid: int | None = None
    project_id: int
    status: str = ""
    ref: str = ""
    sha: str = ""
    source: str | None = None
    web_url: str = ""
    created_at: str | None = None
    updated_at: str | None = None
