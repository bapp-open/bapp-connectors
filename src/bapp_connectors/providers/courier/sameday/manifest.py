"""
Sameday courier provider manifest — declares capabilities, auth, rate limits.
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
    name="sameday",
    family=ProviderFamily.COURIER,
    display_name="Sameday",
    description="Sameday courier integration for AWB generation, tracking, and shipment management.",
    base_url="https://api.sameday.ro/api/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="username", label="API Username", sensitive=False),
            CredentialField(name="password", label="API Password", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="pickup_point_id",
                label="Default Pickup Point ID",
                field_type=FieldType.INT,
                required=False,
                help_text="If not set, the default pickup point from the API will be used.",
            ),
            SettingsField(
                name="service_id",
                label="Default Service ID",
                field_type=FieldType.INT,
                default=7,
                help_text="Sameday service ID. Default: 7 (24h).",
            ),
            SettingsField(
                name="cod_source",
                label="Source for COD figures",
                field_type=FieldType.SELECT,
                choices=["email", "api", "both"],
                default="email",
                help_text=(
                    "Where the cash-on-delivery amounts are read from. "
                    "'email': the 'Ramburs de transferat' XLSX Sameday mails out, the only "
                    "source carrying the payout date, but it depends on the mail arriving. "
                    "'api': delivered COD parcels read from this account, independent of the "
                    "inbox, but booked at the delivery date rather than the payout date. "
                    "'both': run the two together; they cannot double an income."
                ),
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
