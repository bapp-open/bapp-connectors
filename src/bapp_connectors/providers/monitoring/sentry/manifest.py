"""Sentry provider manifest — REST API v0 with an organization or user auth token."""

from bapp_connectors.core.capabilities import IssueTriageCapability, ProjectProvisioningCapability, WebhookCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
    WebhookConfig,
)
from bapp_connectors.core.ports import MonitoringPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="sentry",
    family=ProviderFamily.MONITORING,
    display_name="Sentry",
    description="Sentry (sentry.io or self-hosted): projects, error issues, event stats and issue triage.",
    # Placeholder: the real host comes from per-connection credentials, as with GitLab.
    base_url="https://sentry.example.net/",
    allow_multiple=True,
    # Forms use a 24-column grid (tests/core/test_manifest_layout.py): every row adds up to 24.
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="host",
                label="Server",
                role="endpoint",
                default="sentry.io",
                help_text="Hostname only, e.g. sentry.io or sentry.example.net",
                colspan=24,
            ),
            CredentialField(name="organization", label="Organization slug", colspan=24),
            CredentialField(
                name="token",
                label="Auth token",
                sensitive=True,
                help_text="Organization token from an internal integration, or a user auth token with "
                "org:read project:read event:read event:write",
                colspan=24,
            ),
            CredentialField(
                name="webhook_secret",
                label="Webhook client secret",
                sensitive=True,
                required=False,
                help_text="Client secret of the internal integration that sends webhooks",
                colspan=24,
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="verify_ssl",
                label="Verify TLS certificate",
                field_type=FieldType.BOOL,
                default=True,
                colspan=12,
            ),
            SettingsField(name="timeout", label="Timeout (seconds)", field_type=FieldType.INT, default=30, colspan=12),
            SettingsField(
                name="stats_period",
                label="Stats period",
                field_type=FieldType.SELECT,
                choices=["24h", "14d"],
                default="14d",
                help_text="Issue stats window; Sentry's issues endpoint accepts only '' (none), '24h' and '14d'",
                colspan=12,
            ),
            SettingsField(
                name="environment",
                label="Environment",
                field_type=FieldType.STR,
                default="",
                help_text="Only issues seen in this environment; empty = all",
                colspan=12,
            ),
            SettingsField(
                name="default_team",
                label="Default team",
                field_type=FieldType.STR,
                default="",
                help_text="Team slug that owns projects created from the host application (Settings → Teams)",
                colspan=24,
            ),
        ],
    ),
    capabilities=[MonitoringPort, IssueTriageCapability, WebhookCapability, ProjectProvisioningCapability],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        base_delay=1.0,
        max_delay=30.0,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",
        signature_header="Sentry-Hook-Signature",
        events=[
            "error_issue.created",
            "error_issue.resolved",
            "error_issue.unresolved",
            "error_issue.ignored",
            "error_issue.assigned",
        ],
    ),
)
