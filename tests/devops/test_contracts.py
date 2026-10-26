import pytest
from pydantic import ValidationError

from bapp_connectors.core.capabilities import IssueManagementCapability
from bapp_connectors.core.dto import Issue, Repository
from bapp_connectors.core.ports import DevOpsPort


def test_repository_defaults():
    repo = Repository(ref="12", name="aio", full_path="bapp-cloud/aio")
    assert repo.archived is False and repo.topics == [] and repo.open_issues_count is None


def test_issue_requires_number():
    with pytest.raises(ValidationError):
        Issue(ref="12", title="x")


def test_port_is_abstract():
    with pytest.raises(TypeError):
        DevOpsPort()
    assert {
        "list_projects",
        "get_project",
        "list_issues",
        "get_issue",
        "list_merge_requests",
        "list_commits",
        "list_pipelines",
    } <= set(DevOpsPort.__abstractmethods__)
    assert {"create_issue", "update_issue", "close_issue", "reopen_issue", "add_issue_comment"} == set(
        IssueManagementCapability.__abstractmethods__
    )
