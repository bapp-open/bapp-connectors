"""
DPD Romania provider manifest — web API https://api.dpd.ro/v1 (the Speedy/DPD BG platform).

Source: the official reference https://api.dpd.ro/api/docs/ and its JSON Schema bundle
(https://api.dpd.ro/v1/schema). No token: userName/password travel in every body.
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

DPD_API_URL = "https://api.dpd.ro/v1/"
ROMANIA_ID = 642

manifest = ProviderManifest(
    name="dpd",
    family=ProviderFamily.COURIER,
    display_name="DPD Romania",
    description="DPD Romania — shipments (AWB), labels, tracking and cancellation.",
    base_url=DPD_API_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="username", label="API username"),
            CredentialField(name="password", label="API password", sensitive=True),
            CredentialField(
                name="client_id",
                label="Sender client ID",
                required=False,
                help_text="The sending object (from /client/contract). Empty: the user's default object.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="service_id",
                label="Service ID",
                field_type=FieldType.INT,
                default=2505,
                help_text="DPD service id; 2505 = DPD STANDARD. The contract's services: /services.",
            ),
            SettingsField(
                name="payer",
                label="Shipping paid by",
                field_type=FieldType.SELECT,
                choices=["SENDER", "RECIPIENT"],
                default="SENDER",
            ),
            SettingsField(
                name="paper_size",
                label="Label size",
                field_type=FieldType.SELECT,
                choices=["A6", "A4", "A4_4xA6"],
                default="A6",
            ),
            SettingsField(
                name="package",
                label="Package type",
                field_type=FieldType.STR,
                default="BOX",
                help_text="Free text required by DPD (max 50), e.g. BOX, ENVELOPE.",
            ),
        ],
    ),
    capabilities=[CourierPort],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
