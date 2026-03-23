"""
GoIP SMS gateway provider manifest — declares capabilities, auth, rate limits.

GoIP is a physical GSM gateway device that exposes an HTTP interface for sending SMS.
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="goip",
    family=ProviderFamily.MESSAGING,
    display_name="GoIP",
    description="GoIP GSM gateway for sending SMS via a physical device over HTTP.",
    base_url="http://localhost/default/en_US/",
    auth=AuthConfig(
        strategy=AuthStrategy.BASIC,
        required_fields=[
            CredentialField(name="username", label="Username", sensitive=False),
            CredentialField(name="password", label="Password", sensitive=True),
            CredentialField(
                name="ip",
                label="Device IP",
                sensitive=False,
                help_text="IP address or hostname of the GoIP device.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="line",
                label="SIM Line",
                field_type=FieldType.INT,
                default=1,
                help_text="GSM line/SIM slot to use for sending (default: 1).",
            ),
            SettingsField(
                name="max_retries",
                label="Max Retries",
                field_type=FieldType.INT,
                default=0,
                help_text="Number of retries when the line is busy (default: 0).",
            ),
            SettingsField(
                name="base_url",
                label="Custom Base URL",
                field_type=FieldType.STR,
                required=False,
                help_text="Override the auto-generated base URL (http://{ip}/default/en_US/).",
            ),
        ],
    ),
    capabilities=[
        MessagingPort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=1,
        burst=3,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.LINEAR,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
