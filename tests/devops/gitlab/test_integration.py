"""Live GitLab tests. Read-only unless GITLAB_ALLOW_WRITES=1.

GITLAB_PROJECT (a full path such as group/project) picks the project used for the
per-project reads and the write test; by default the first project the token sees.
"""

import os

import pytest

from bapp_connectors.core.dto import Issue, IssueDraft, Pipeline, Repository
from bapp_connectors.providers.devops.gitlab import GitLabAdapter

CREDENTIALS = {
    "host": os.getenv("GITLAB_HOST", ""),
    "token": os.getenv("GITLAB_TOKEN", ""),
}

skip_unless_gitlab = pytest.mark.skipif(
    not all(CREDENTIALS.values()),
    reason="set GITLAB_HOST and GITLAB_TOKEN to run",
)
skip_unless_writes = pytest.mark.skipif(
    os.getenv("GITLAB_ALLOW_WRITES") != "1",
    reason="set GITLAB_ALLOW_WRITES=1 to run write tests (creates and closes an issue)",
)

pytestmark = [pytest.mark.integration, skip_unless_gitlab]


@pytest.fixture
def adapter():
    return GitLabAdapter(credentials=CREDENTIALS, config={})


@pytest.fixture
def project_path(adapter):
    configured = os.getenv("GITLAB_PROJECT", "")
    if configured:
        return configured
    projects = adapter.list_projects().items
    assert projects, "the token must see at least one project"
    return projects[0].full_path


def test_connection(adapter):
    result = adapter.test_connection()
    assert result.success is True, result.message


def test_list_projects(adapter):
    page = adapter.list_projects()
    assert len(page.items) >= 1
    for repo in page.items:
        assert isinstance(repo, Repository)
        assert repo.ref.isdigit()


def test_get_project_by_path(adapter, project_path):
    repo = adapter.get_project(project_path)
    assert isinstance(repo, Repository)
    assert repo.full_path == project_path
    assert repo.ref.isdigit()


def test_list_issues_and_pipelines(adapter, project_path):
    issues = adapter.list_issues(project_path)
    assert all(isinstance(issue, Issue) for issue in issues.items)
    pipelines = adapter.list_pipelines(project_path)
    assert all(isinstance(pipeline, Pipeline) for pipeline in pipelines.items)


@skip_unless_writes
def test_create_and_close_issue(adapter, project_path):
    issue = adapter.create_issue(
        project_path,
        IssueDraft(title="[bapp-connectors test]", description="Created by the live integration test; safe to delete."),
    )
    try:
        assert issue.number > 0
        assert issue.state == "opened"
    finally:
        closed = adapter.close_issue(project_path, issue.number)
    assert closed.state == "closed"
