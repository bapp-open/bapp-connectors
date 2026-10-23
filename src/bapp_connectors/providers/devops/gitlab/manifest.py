"""GitLab provider manifest — REST API v4 with a personal, group or project access token."""

from bapp_connectors.core.capabilities import IssueManagementCapability, WebhookCapability
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
from bapp_connectors.core.ports import DevOpsPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="gitlab",
    family=ProviderFamily.DEVOPS,
    display_name="GitLab",
    description="GitLab (gitlab.com or self-managed): projects, issues, merge requests, commits and pipelines.",
    # Placeholder: the real host comes from per-connection credentials, as with cPanel.
    base_url="https://gitlab.example.net/",
    allow_multiple=True,
    # Forms use a 24-column grid (tests/core/test_manifest_layout.py): every row adds up to 24.
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="host",
                label="Server",
                role="endpoint",
                default="gitlab.com",
                help_text="Hostname only, e.g. gitlab.com or git.example.net",
                colspan=24,
            ),
            CredentialField(
                name="token",
                label="Access token",
                sensitive=True,
                help_text="Personal, group or project access token with the api scope (read_api for read-only)",
                colspan=24,
            ),
            CredentialField(
                name="webhook_secret",
                label="Webhook secret token",
                sensitive=True,
                required=False,
                help_text="The 'Secret token' entered on the GitLab webhook",
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
                name="groups",
                label="Groups",
                field_type=FieldType.STR,
                default="",
                help_text="Comma-separated group paths to index, e.g. bapp-cloud,cbsoft; "
                "empty = everything the token can see",
                colspan=24,
            ),
            SettingsField(
                name="include_archived",
                label="Include archived projects",
                field_type=FieldType.BOOL,
                default=False,
                colspan=24,
            ),
        ],
    ),
    capabilities=[DevOpsPort, IssueManagementCapability, WebhookCapability],
    rate_limit=RateLimitConfig(requests_per_second=10, burst=20),
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
        signature_method="plain-token",
        signature_header="X-Gitlab-Token",
        events=[
            "issue.opened",
            "issue.updated",
            "issue.closed",
            "issue.reopened",
            "issue.commented",
            "merge_request.opened",
            "merge_request.merged",
            "merge_request.closed",
            "repository.push",
            "pipeline.succeeded",
            "pipeline.failed",
        ],
    ),
)
