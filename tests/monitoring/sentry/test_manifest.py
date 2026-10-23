from bapp_connectors.core.capabilities import IssueTriageCapability, WebhookCapability
from bapp_connectors.core.ports import MonitoringPort
from bapp_connectors.providers.monitoring.sentry.manifest import manifest


def test_manifest_identity():
    assert (manifest.name, manifest.family.value, manifest.allow_multiple) == ("sentry", "monitoring", True)
    assert [f.name for f in manifest.auth.required_fields] == ["host", "organization", "token", "webhook_secret"]
    fields = {f.name: f for f in manifest.auth.required_fields}
    assert fields["token"].sensitive and fields["webhook_secret"].sensitive
    assert not fields["webhook_secret"].required
    assert manifest.webhooks.signature_method == "hmac-sha256"
    assert manifest.webhooks.signature_header == "Sentry-Hook-Signature"


def test_manifest_endpoint_and_settings():
    host = manifest.auth.required_fields[0]
    assert host.role == "endpoint" and host.default == "sentry.io"
    settings = {f.name: f.default for f in manifest.settings.fields}
    assert settings == {"verify_ssl": True, "timeout": 30, "stats_period": "14d", "environment": ""}


def test_manifest_capabilities_and_events():
    assert manifest.capabilities == [MonitoringPort, IssueTriageCapability, WebhookCapability]
    assert manifest.webhooks.events == [
        "error_issue.created",
        "error_issue.resolved",
        "error_issue.unresolved",
        "error_issue.ignored",
        "error_issue.assigned",
    ]
    assert (manifest.rate_limit.requests_per_second, manifest.rate_limit.burst) == (5, 10)
