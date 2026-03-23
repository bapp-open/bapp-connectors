"""
Colete Online courier provider manifest — declares capabilities, auth, rate limits.
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
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="colete_online",
    family=ProviderFamily.COURIER,
    display_name="Colete Online",
    description="Colete Online courier aggregator integration for AWB generation, tracking, and shipment management.",
    base_url="https://api.colete-online.ro/v1/",
    auth=AuthConfig(
        strategy=AuthStrategy.OAUTH2,
        required_fields=[
            CredentialField(name="client_id", label="Client ID", sensitive=False),
            CredentialField(name="client_secret", label="Client Secret", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="staging",
                label="Use Staging Environment",
                field_type=FieldType.BOOL,
                default=True,
                help_text="When enabled, orders are created in the staging environment.",
            ),
        ],
    ),
    capabilities=[
        CourierPort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=5,
        burst=10,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
