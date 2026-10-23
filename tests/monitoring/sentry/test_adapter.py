"""Sentry adapter tests against the scrubbed REST captures."""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from bapp_connectors.core.capabilities import IssueTriageCapability, WebhookCapability
from bapp_connectors.core.dto import WebhookEventType
from bapp_connectors.core.dto.monitoring import ErrorIssue, MonitoredProject, MonitoredProjectStats
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.registry import registry
from bapp_connectors.providers.monitoring.sentry.adapter import SentryAdapter
from tests.fake_http import FakeHttpClient, fake_response
from tests.monitoring.contract import MonitoringContractTests
from tests.monitoring.sentry.conftest import load

CREDENTIALS = {"host": "sentry.example.net", "organization": "example-org", "token": "not-a-real-token"}
NEXT = '<https://s/api/0/x/?cursor=1:100:0>; rel="next"; results="{}"; cursor="1:100:0"'
LAST = {"Link": NEXT.format("false")}
MORE = {"Link": NEXT.format("true")}


def build_http() -> FakeHttpClient:
    """Rules are substring-matched in order: the most specific paths come first."""
    http = FakeHttpClient()
    http.add("GET", "/stats_v2/", fake_response(load("stats_v2")))
    http.add("GET", "/projects/example-org/aio-backend/issues/", fake_response(load("issues"), MORE))
    http.add("GET", "/projects/example-org/aio-backend/", fake_response(load("project")))
    http.add("GET", "/organizations/example-org/projects/", fake_response(load("projects"), LAST))
    http.add("GET", "/organizations/example-org/", fake_response({"slug": "example-org", "name": "Example Org"}))
    http.add("GET", "/issues/23296/", fake_response(load("issue")))
    http.add("PUT", "/issues/23296/", fake_response(load("issue")))
    return http


@pytest.fixture
def http():
    return build_http()


@pytest.fixture
def adapter(http):
    return SentryAdapter(credentials=CREDENTIALS, http_client=http, config={})


class TestSentryContract(MonitoringContractTests):
    project_ref = "aio-backend"

    @pytest.fixture
    def adapter(self):
        return SentryAdapter(credentials=CREDENTIALS, http_client=build_http(), config={})


# ── construction ──


def test_builds_its_own_http_client_when_none_injected():
    adapter = SentryAdapter(credentials=CREDENTIALS)
    assert isinstance(adapter.http_client, ResilientHttpClient)
    assert adapter.client.http is adapter.http_client


def test_injected_http_client_is_exposed(adapter, http):
    assert adapter.http_client is http


def test_config_parsing():
    adapter = SentryAdapter(
        credentials={**CREDENTIALS, "host": " sentry.example.net/ "},
        http_client=FakeHttpClient(),
        config={"verify_ssl": False, "timeout": 5, "stats_period": "24h", "environment": " production "},
    )
    assert adapter.stats_period == "24h" and adapter.environment == "production"
    assert adapter.client.verify_ssl is False and adapter.client.timeout == 5
    assert adapter.client.host == "sentry.example.net" and adapter.client.organization == "example-org"


def test_config_defaults(adapter):
    assert adapter.stats_period == "14d" and adapter.environment == ""


def test_validate_credentials_missing_organization(http):
    creds = {"host": "sentry.example.net", "token": "x"}
    assert SentryAdapter(credentials=creds, http_client=http).validate_credentials() is False


# ── connection ──


def test_test_connection_reports_organization(adapter, http):
    result = adapter.test_connection()
    assert result.success is True and result.message == "Connected."
    assert result.details == {"organization": "example-org", "name": "Example Org"}
    assert http.last_call().path == "https://sentry.example.net/api/0/organizations/example-org/"


def test_test_connection_bad_token():
    http = FakeHttpClient()
    http.add("GET", "/organizations/", fake_response({"detail": "Invalid token"}, status=401))
    result = SentryAdapter(credentials=CREDENTIALS, http_client=http).test_connection()
    assert result.success is False and result.message


# ── reads ──


def test_list_projects(adapter):
    result = adapter.list_projects()
    assert [p.ref for p in result.items] == ["aio-backend", "example-api", "example-web"]
    assert result.has_more is False and result.cursor is None
    assert result.items[0].web_url == "https://sentry.example.net/organizations/example-org/projects/aio-backend/"


def test_get_project(adapter):
    project = adapter.get_project("aio-backend")
    assert isinstance(project, MonitoredProject) and project.ref == "aio-backend" and project.extra["id"] == "3"


def test_list_issues_defaults_and_cursor(adapter, http):
    result = adapter.list_issues("aio-backend", cursor="1:0:0")
    assert len(result.items) == 3 and result.has_more is True and result.cursor == "1:100:0"
    params = http.last_call().kwargs["params"]
    assert params == {"query": "is:unresolved", "statsPeriod": "14d", "sort": "date", "cursor": "1:0:0"}


def test_list_issues_passes_environment_and_period(http):
    adapter = SentryAdapter(
        credentials=CREDENTIALS, http_client=http, config={"environment": "production", "stats_period": "90d"}
    )
    adapter.list_issues("aio-backend", query="is:resolved", period="24h", sort="freq")
    params = http.last_call().kwargs["params"]
    # The argument wins over the config `stats_period`: that one is the caller's default.
    assert params["statsPeriod"] == "24h" and params["environment"] == "production"
    assert params["query"] == "is:resolved" and params["sort"] == "freq"


def test_get_issue(adapter):
    issue = adapter.get_issue("23296")
    assert isinstance(issue, ErrorIssue) and issue.short_id == "AIO-BACKEND-3XK" and issue.ref == "aio-backend"


def test_get_project_stats_resolves_numeric_id(adapter, http):
    stats = adapter.get_project_stats("aio-backend", period="7d")
    assert isinstance(stats, MonitoredProjectStats)
    assert (stats.ref, stats.period, stats.events, stats.errors_received, stats.errors_rejected) == (
        "aio-backend",
        "7d",
        5,
        16,
        11,
    )
    params = http.last_call().kwargs["params"]
    assert params["project"] == "3"
    assert params["statsPeriod"] == "7d"


# ── triage ──


def test_resolve_issue_sends_status(adapter, http):
    issue = adapter.resolve_issue("23296")
    assert isinstance(issue, ErrorIssue)
    assert http.calls[-1].method == "PUT"
    assert http.calls[-1].kwargs["json"] == {"status": "resolved"}


def test_unresolve_issue(adapter, http):
    assert isinstance(adapter.unresolve_issue("23296"), ErrorIssue)
    assert http.last_call().kwargs["json"] == {"status": "unresolved"}


def test_ignore_issue_indefinitely(adapter, http):
    adapter.ignore_issue("23296")
    assert http.last_call().kwargs["json"] == {"status": "ignored", "statusDetails": {}}


def test_ignore_issue_until(adapter, http):
    until = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    adapter.ignore_issue("23296", until=until)
    assert http.last_call().kwargs["json"] == {
        "status": "ignored",
        "statusDetails": {"ignoreUntil": "2026-11-01T12:00:00+00:00"},
    }


def test_assign_issue(adapter, http):
    adapter.assign_issue("23296", "dev@example.net")
    assert http.last_call().method == "PUT"
    assert http.last_call().kwargs["json"] == {"assignedTo": "dev@example.net"}


# ── webhooks ──


def test_verify_webhook_hmac(http):
    body = b'{"action":"created"}'
    signature = hmac.new(b"sec", body, hashlib.sha256).hexdigest()
    adapter = SentryAdapter(credentials={**CREDENTIALS, "webhook_secret": "sec"}, http_client=http)
    assert adapter.verify_webhook({"Sentry-Hook-Signature": signature}, body) is True
    assert adapter.verify_webhook({"sentry-hook-signature": signature}, body) is True
    assert adapter.verify_webhook({"SENTRY-HOOK-SIGNATURE": signature}, body) is True
    assert adapter.verify_webhook({"Sentry-Hook-Signature": signature}, body + b" ") is False
    assert adapter.verify_webhook({}, body) is False


def test_verify_webhook_explicit_secret_wins(adapter):
    body = b"{}"
    signature = hmac.new(b"given", body, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook({"Sentry-Hook-Signature": signature}, body, secret="given") is True


def test_verify_webhook_without_secret_is_false(adapter):
    body = b"{}"
    signature = hmac.new(b"", body, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook({"Sentry-Hook-Signature": signature}, body) is False


def test_parse_webhook(adapter):
    body = json.dumps(load("hook_issue_created")).encode()
    event = adapter.parse_webhook({"Sentry-Hook-Resource": "issue", "Request-ID": "r-1"}, body)
    assert event.event_type == WebhookEventType.ERROR_ISSUE_CREATED and event.provider == "sentry"
    assert event.idempotency_key == "r-1"


def test_register_webhook_not_supported(adapter):
    with pytest.raises(NotImplementedError):
        adapter.register_webhook("https://hooks.example.net/x")


# ── registry ──


def test_registry():
    import bapp_connectors.providers.monitoring.sentry  # noqa: F401

    assert registry.is_registered("monitoring", "sentry")
    assert any(m.name == "sentry" for m in registry.list_providers(capability=IssueTriageCapability))
    assert any(m.name == "sentry" for m in registry.list_providers(capability=WebhookCapability))
