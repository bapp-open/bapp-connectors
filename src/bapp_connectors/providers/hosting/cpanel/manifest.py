"""cPanel provider manifest — UAPI over HTTPS with an account API token."""

from bapp_connectors.core.capabilities import MailboxCapability, PanelLinkCapability
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
from bapp_connectors.core.ports import DnsPort, HostingPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="cpanel",
    family=ProviderFamily.HOSTING,
    display_name="cPanel",
    description="cPanel hosting account managed through UAPI: domains, resources, mailboxes and DNS.",
    # Placeholder: the real host comes from per-connection credentials, as with pfSense and WooCommerce.
    base_url="https://cpanel.example.net:2083/",
    allow_multiple=True,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="hostname",
                label="Server",
                role="endpoint",
                help_text="Hostname of the cPanel server, e.g. cpanel.example.net (no scheme, no port).",
            ),
            CredentialField(name="username", label="cPanel user"),
            CredentialField(
                name="token",
                label="API token",
                sensitive=True,
                help_text="Created in cPanel under Security > Manage API Tokens.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(name="port", label="Port", field_type=FieldType.INT, default=2083),
            SettingsField(name="webmail_port", label="Webmail port", field_type=FieldType.INT, default=2096),
            SettingsField(name="verify_ssl", label="Verify TLS certificate", field_type=FieldType.BOOL, default=True),
            SettingsField(name="timeout", label="Timeout (seconds)", field_type=FieldType.INT, default=30),
        ],
    ),
    capabilities=[HostingPort, DnsPort, MailboxCapability, PanelLinkCapability],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        base_delay=1.0,
        max_delay=30.0,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(supported=False),
)
