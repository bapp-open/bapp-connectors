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
    assert settings == {
        "verify_ssl": True,
        "timeout": 30,
        "stats_period": "14d",
        "environment": "",
        "default_team": "",
    }


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


def test_stats_period_is_a_select_of_the_values_the_issues_endpoint_accepts():
    from bapp_connectors.core.types import FieldType

    field = next(f for f in manifest.settings.fields if f.name == "stats_period")
    assert field.field_type == FieldType.SELECT
    assert field.choices == ["24h", "14d"] and field.default == "14d"
    assert "24h" in field.help_text and "14d" in field.help_text


def test_default_team_setting():
    from bapp_connectors.core.types import FieldType

    field = next(f for f in manifest.settings.fields if f.name == "default_team")
    assert field.field_type == FieldType.STR and field.default == "" and field.colspan == 24
    assert field.label == "Default team" and "Team slug" in field.help_text
