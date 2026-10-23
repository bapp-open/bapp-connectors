"""Live Sentry tests. Read-only unless SENTRY_ALLOW_WRITES=1.

SENTRY_PROJECT (a project slug, default `aio-backend`) picks the project used for the
per-project reads and the write test.
"""

import os

import pytest

from bapp_connectors.core.dto import ErrorIssue, MonitoredProject, MonitoredProjectStats
from bapp_connectors.providers.monitoring.sentry import SentryAdapter

CREDENTIALS = {
    "host": os.getenv("SENTRY_HOST", ""),
    "organization": os.getenv("SENTRY_ORG", ""),
    "token": os.getenv("SENTRY_TOKEN", ""),
}
PROJECT = os.getenv("SENTRY_PROJECT", "aio-backend")

skip_unless_sentry = pytest.mark.skipif(
    not all(CREDENTIALS.values()),
    reason="set SENTRY_HOST, SENTRY_ORG and SENTRY_TOKEN to run",
)
skip_unless_writes = pytest.mark.skipif(
    os.getenv("SENTRY_ALLOW_WRITES") != "1",
    reason="set SENTRY_ALLOW_WRITES=1 to run write tests (resolves and unresolves an issue)",
)

pytestmark = [pytest.mark.integration, skip_unless_sentry]


@pytest.fixture
def adapter():
    return SentryAdapter(credentials=CREDENTIALS, config={})


def test_connection(adapter):
    result = adapter.test_connection()
    assert result.success is True, result.message
    assert result.details["organization"] == CREDENTIALS["organization"]


def test_list_projects(adapter):
    page = adapter.list_projects()
    assert len(page.items) >= 1
    for project in page.items:
        assert isinstance(project, MonitoredProject)
        assert project.ref == project.slug


def test_get_project(adapter):
    project = adapter.get_project(PROJECT)
    assert isinstance(project, MonitoredProject)
    assert project.ref == PROJECT


def test_list_issues_unresolved(adapter):
    page = adapter.list_issues(PROJECT, query="is:unresolved", period="14d")
    for issue in page.items:
        assert isinstance(issue, ErrorIssue)
        assert issue.id
        assert issue.status == "unresolved"
    if page.items:
        fetched = adapter.get_issue(page.items[0].id)
        assert fetched.id == page.items[0].id


def test_get_project_stats(adapter):
    stats = adapter.get_project_stats(PROJECT, period="24h")
    assert isinstance(stats, MonitoredProjectStats)
    assert stats.ref == PROJECT
    assert stats.period == "24h"
    assert stats.events >= 0
    assert stats.errors_received >= 0


@skip_unless_writes
def test_resolve_and_unresolve(adapter):
    issues = adapter.list_issues(PROJECT, query="is:unresolved", period="14d").items
    if not issues:
        pytest.skip(f"no unresolved issue in {PROJECT} to triage")
    issue_id = issues[0].id
    try:
        resolved = adapter.resolve_issue(issue_id)
        assert resolved.status == "resolved"
    finally:
        restored = adapter.unresolve_issue(issue_id)
    assert restored.status == "unresolved"
