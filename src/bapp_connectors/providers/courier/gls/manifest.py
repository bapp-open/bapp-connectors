"""
GLS courier provider manifest — declares capabilities, auth, rate limits.
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
    name="gls",
    family=ProviderFamily.COURIER,
    display_name="GLS",
    description="GLS courier integration for AWB generation, tracking, and shipment management.",
    base_url="https://api.mygls.ro/ParcelService.svc/json/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="username", label="API Username", sensitive=False),
            CredentialField(name="password", label="API Password", sensitive=True),
            CredentialField(name="client_number", label="Client Number", sensitive=False),
            CredentialField(name="country", label="Country Code (RO, HU, HR, CZ, SI, SK, RS)", sensitive=False),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="printer_type",
                label="AWB Printer Format",
                field_type=FieldType.SELECT,
                default="Connect",
                choices=["A4_2x2", "A4_4x1", "Connect", "Thermo"],
                help_text="Label format for AWB printing.",
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
