"""pfSense provider manifest — XML-RPC (`pfsense.exec_php`) over HTTPS with basic auth."""

from bapp_connectors.core.capabilities import DnsAllowlistCapability
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
from bapp_connectors.core.ports import NetworkPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="pfsense",
    family=ProviderFamily.NETWORK,
    display_name="pfSense",
    description="pfSense / pfSense Plus firewall managed through its built-in XML-RPC interface.",
    base_url="https://pfsense.example:8885/",  # placeholder; real hosts come from the `endpoints` setting
    allow_multiple=True,
    auth=AuthConfig(
        strategy=AuthStrategy.BASIC,
        required_fields=[
            CredentialField(name="username", label="Username", help_text="A pfSense admin account."),
            CredentialField(name="password", label="Password", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="endpoints",
                label="Endpoints",
                field_type=FieldType.TEXTAREA,
                required=True,
                help_text="Base URLs separated by commas (or one per line), tried in order, "
                "e.g. https://5.2.251.35:8885, https://86.121.185.49:8885 — one per WAN when multi-homed.",
            ),
            SettingsField(
                name="verify_ssl",
                label="Verify TLS certificate",
                field_type=FieldType.BOOL,
                default=False,
                help_text="pfSense ships a self-signed certificate; leave off unless you installed a trusted one.",
            ),
            SettingsField(
                name="timeout",
                label="Timeout (seconds)",
                field_type=FieldType.INT,
                default=20,
            ),
        ],
    ),
    capabilities=[NetworkPort, DnsAllowlistCapability],
    rate_limit=RateLimitConfig(requests_per_second=2, burst=4),
    retry=RetryConfig(
        max_retries=0,  # failover between endpoints replaces per-request retries
        backoff=BackoffStrategy.NONE,
        retryable_status_codes=[],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(supported=False),
)
