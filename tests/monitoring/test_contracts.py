import pytest
from pydantic import ValidationError

from bapp_connectors.core.capabilities import IssueTriageCapability, ProjectProvisioningCapability
from bapp_connectors.core.dto import ErrorIssue, MonitoredProject, MonitoringTeam, ProjectKey
from bapp_connectors.core.ports import MonitoringPort


def test_error_issue_defaults():
    issue = ErrorIssue(ref="aio-backend", id="1", short_id="AIO-1", title="x")
    assert issue.level == "error" and issue.status == "unresolved"
    assert issue.count == 0 and issue.user_count == 0 and issue.is_unhandled is False


def test_monitored_project_defaults():
    project = MonitoredProject(ref="aio-backend", name="AIO", slug="aio-backend")
    assert project.is_active is True and project.platform == "" and project.extra == {}


def test_error_issue_requires_ids():
    with pytest.raises(ValidationError):
        ErrorIssue(ref="p", title="x")


def test_port_is_abstract():
    with pytest.raises(TypeError):
        MonitoringPort()
    assert {"list_projects", "get_project", "list_issues", "get_issue", "get_project_stats"} <= set(
        MonitoringPort.__abstractmethods__
    )
    assert {"resolve_issue", "unresolve_issue", "ignore_issue", "assign_issue"} == set(
        IssueTriageCapability.__abstractmethods__
    )


def test_provisioning_capability_is_abstract():
    with pytest.raises(TypeError):
        ProjectProvisioningCapability()
    assert {"list_teams", "create_project", "list_keys"} == set(ProjectProvisioningCapability.__abstractmethods__)


def test_project_key_defaults():
    key = ProjectKey(id="k1")
    assert key.label == "" and key.dsn_public == "" and key.dsn_secret == ""
    assert key.is_active is True and key.extra == {}


def test_monitoring_team_requires_fields():
    team = MonitoringTeam(ref="backend", slug="backend", name="Backend")
    assert (team.ref, team.slug, team.name) == ("backend", "backend", "Backend")
    with pytest.raises(ValidationError):
        MonitoringTeam(ref="backend")
