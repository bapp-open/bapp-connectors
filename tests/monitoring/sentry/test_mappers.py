"""Sentry mappers against the anonymized REST captures and hand-written webhook payloads."""

from datetime import UTC, datetime

import pytest

from bapp_connectors.core.dto import WebhookEventType
from bapp_connectors.providers.monitoring.sentry.mappers import (
    map_issue,
    map_project,
    map_stats,
    webhook_event_from_sentry,
)
from bapp_connectors.providers.monitoring.sentry.models import SentryIssue, SentryProject

HOST = "sentry.example.net"
ORG = "example-org"
HEADERS = {
    "Sentry-Hook-Resource": "issue",
    "Sentry-Hook-Signature": "0" * 64,
    "Request-ID": "d5d4a5b0-4e8b-4a43-9bb2-1c3f0e5a7b21",
}

# ── Raw models ──


def test_models_accept_recorded_payloads(projects_raw, project_raw, issues_raw, issue_raw):
    assert [SentryProject.model_validate(p).slug for p in projects_raw] == ["aio-backend", "example-api", "example-web"]
    assert SentryProject.model_validate(project_raw).status == "active"
    assert SentryIssue.model_validate(issue_raw).assignedTo.email == "user@example.com"
    assert [SentryIssue.model_validate(i).count for i in issues_raw] == ["3", "84", "1"]


# ── Projects ──


def test_map_project(projects_raw):
    project = map_project(projects_raw[0], HOST, ORG)
    assert project.ref == "aio-backend" and project.slug == "aio-backend"
    assert project.name == "aio-backend"
    assert project.platform == "python-django"
    assert project.web_url == "https://sentry.example.net/organizations/example-org/projects/aio-backend/"
    assert project.is_active is True
    assert project.extra == {"id": "3"}


def test_map_project_detail(project_raw):
    project = map_project(project_raw, HOST, ORG)
    assert project.ref == "aio-backend" and project.is_active is True and project.extra == {"id": "3"}


def test_map_project_inactive_status():
    project = map_project({"id": "9", "slug": "old", "name": "Old", "status": "pending_deletion"}, HOST, ORG)
    assert project.is_active is False


def test_map_project_tolerates_minimal_payload():
    project = map_project({"slug": "x", "platform": None}, HOST, ORG)
    assert project.ref == "x" and project.name == "x" and project.platform == ""
    assert project.extra == {"id": ""}


# ── Issues ──


def test_map_issue(issue_raw):
    issue = map_issue(issue_raw)
    assert issue.ref == "aio-backend"
    assert issue.id == "23296"
    assert issue.short_id == "AIO-BACKEND-3XK"
    assert issue.title == "ExampleError: example message 1"
    assert issue.culprit == "example.module1 in handler"
    assert issue.level == "error" and issue.status == "unresolved"
    assert issue.count == 3 and isinstance(issue.count, int)
    assert issue.user_count == 1
    assert issue.first_seen == datetime(2026, 10, 23, 7, 57, 53, 537894, tzinfo=UTC)
    assert issue.last_seen == datetime(2026, 10, 23, 7, 58, 7, tzinfo=UTC)
    assert issue.is_unhandled is True
    assert issue.assigned_to == "user@example.com"
    assert issue.permalink == "https://sentry.example.net/organizations/example-org/issues/23296/"
    assert set(issue.extra) == {"type", "metadata", "logger", "platform"}
    assert issue.extra["type"] == "error" and issue.extra["platform"] == "python"
    assert issue.extra["metadata"]["type"] == "ExampleError" and issue.extra["logger"] is None


def test_map_issue_list(issues_raw):
    issues = [map_issue(raw) for raw in issues_raw]
    assert [i.id for i in issues] == ["23296", "21832", "23270"]
    assert [i.count for i in issues] == [3, 84, 1]
    assert [i.level for i in issues] == ["error", "info", "error"]
    assert issues[1].culprit.startswith("django.core.management.commands.shell")
    assert issues[1].assigned_to == "" and issues[2].extra["logger"] == "bapp_sdk.helpers.company_info"
    assert all(i.first_seen.tzinfo is not None and i.last_seen.tzinfo is not None for i in issues)


@pytest.mark.parametrize(
    ("assignee", "expected"),
    [
        ({"type": "user", "name": "Example User", "email": "user@example.com"}, "user@example.com"),
        ({"type": "team", "name": "example-team"}, "example-team"),
        ({"type": "user", "name": "", "email": None}, ""),
        (None, ""),
    ],
)
def test_map_issue_assignee(issue_raw, assignee, expected):
    assert map_issue({**issue_raw, "assignedTo": assignee}).assigned_to == expected


def test_map_issue_tolerates_minimal_payload():
    issue = map_issue({"id": 5, "count": None, "firstSeen": "not a date", "culprit": None, "project": None})
    assert issue.id == "5" and issue.ref == "" and issue.short_id == "" and issue.title == ""
    assert issue.count == 0 and issue.user_count == 0 and issue.culprit == ""
    assert issue.first_seen is None and issue.last_seen is None
    assert issue.level == "error" and issue.status == "unresolved" and issue.assigned_to == ""
    assert issue.extra == {"type": None, "metadata": {}, "logger": None, "platform": None}


# ── Stats ──


def test_map_stats(stats_v2_raw):
    stats = map_stats(stats_v2_raw, "aio-backend", "24h")
    assert stats.ref == "aio-backend" and stats.period == "24h"
    assert stats.events == 5
    assert stats.errors_received == 16
    assert stats.errors_rejected == 11


def test_map_stats_empty():
    stats = map_stats({"groups": []}, "x", "14d")
    assert (stats.events, stats.errors_received, stats.errors_rejected) == (0, 0, 0)
    assert map_stats({}, "x", "14d").events == 0


def test_map_stats_sums_repeated_outcomes():
    raw = {
        "groups": [
            {"by": {"outcome": "accepted"}, "totals": {"sum(quantity)": 2}},
            {"by": {"outcome": "accepted"}, "totals": {"sum(quantity)": 3}},
            {"by": {"outcome": "rate_limited"}, "totals": {"sum(quantity)": 4}},
            {"by": {}, "totals": {}},
        ]
    }
    stats = map_stats(raw, "x", "24h")
    assert (stats.events, stats.errors_received, stats.errors_rejected) == (5, 9, 4)


# ── Webhooks ──


def test_webhook_created(hook_issue_created):
    event = webhook_event_from_sentry(HEADERS, hook_issue_created)
    assert event.event_type == WebhookEventType.ERROR_ISSUE_CREATED
    assert event.provider == "sentry"
    assert event.provider_event_type == "issue:created"
    assert event.event_id == "d5d4a5b0-4e8b-4a43-9bb2-1c3f0e5a7b21"
    assert event.idempotency_key == "d5d4a5b0-4e8b-4a43-9bb2-1c3f0e5a7b21"
    assert event.payload == hook_issue_created
    assert event.received_at is not None and event.received_at.tzinfo is not None


def test_webhook_resolved(hook_issue_resolved):
    event = webhook_event_from_sentry(HEADERS, hook_issue_resolved)
    assert event.event_type == WebhookEventType.ERROR_ISSUE_RESOLVED
    assert event.provider_event_type == "issue:resolved"


def test_webhook_headers_case_insensitive(hook_issue_resolved):
    headers = {"sentry-hook-resource": "issue", "request-id": "abc"}
    event = webhook_event_from_sentry(headers, hook_issue_resolved)
    assert event.event_type == WebhookEventType.ERROR_ISSUE_RESOLVED
    assert event.event_id == "abc" and event.idempotency_key == "abc"


def test_webhook_key_without_request_id(hook_issue_resolved):
    event = webhook_event_from_sentry({"Sentry-Hook-Resource": "issue"}, hook_issue_resolved)
    assert event.event_id == ""
    assert event.idempotency_key == "resolved:23296"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("created", WebhookEventType.ERROR_ISSUE_CREATED),
        ("resolved", WebhookEventType.ERROR_ISSUE_RESOLVED),
        ("unresolved", WebhookEventType.ERROR_ISSUE_UNRESOLVED),
        ("ignored", WebhookEventType.ERROR_ISSUE_IGNORED),
        ("assigned", WebhookEventType.ERROR_ISSUE_ASSIGNED),
        ("archived", WebhookEventType.UNKNOWN),
        ("", WebhookEventType.UNKNOWN),
    ],
)
def test_webhook_actions(hook_issue_created, action, expected):
    event = webhook_event_from_sentry(HEADERS, {**hook_issue_created, "action": action})
    assert event.event_type == expected
    assert event.provider_event_type == f"issue:{action}"


def test_webhook_non_issue_resource(hook_issue_created):
    headers = {**HEADERS, "Sentry-Hook-Resource": "event_alert"}
    event = webhook_event_from_sentry(headers, hook_issue_created)
    assert event.event_type == WebhookEventType.UNKNOWN
    assert event.provider == "sentry"
    assert event.provider_event_type == "event_alert:created"


def test_webhook_tolerates_empty_payload():
    event = webhook_event_from_sentry({}, None)
    assert event.event_type == WebhookEventType.UNKNOWN
    assert event.payload == {} and event.idempotency_key == ":" and event.provider_event_type == ":"
