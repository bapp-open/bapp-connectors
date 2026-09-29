"""
eColet courier-aggregator manifest.

eColet (panel.ecolet.ro) books shipments with DPD, Cargus, Sameday, FAN Courier,
GLS and others through one account; the courier is chosen per shipment by a
service slug (`dpd_standard`, `sameday_...`). Spec: the OpenAPI file behind
https://panel.ecolet.ro/api/documentation (docs/api-docs.json, v1.0.3).
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

ECOLET_LIVE_URL = "https://panel.ecolet.ro/api/"
ECOLET_STAGING_URL = "https://staging.ecolet.ro/api/"

manifest = ProviderManifest(
    name="ecolet",
    family=ProviderFamily.COURIER,
    display_name="eColet",
    description="eColet courier aggregator — one account for DPD, Cargus, Sameday, FAN Courier, GLS and more.",
    base_url=ECOLET_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="client_id",
                label="OAuth Client ID",
                help_text="From the eColet panel: Cont > Aplicatii OAuth (/account/oauth/clients).",
            ),
            CredentialField(name="client_secret", label="OAuth Client Secret", sensitive=True),
            CredentialField(name="username", label="Account email"),
            CredentialField(name="password", label="Account password", sensitive=True),
            CredentialField(
                name="staging",
                label="Staging",
                required=False,
                default="false",
                help_text="Use staging.ecolet.ro (needs a staging account).",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="service",
                label="Default service",
                field_type=FieldType.STR,
                required=False,
                help_text="eColet service slug, e.g. dpd_standard. Empty: the cheapest service available for the shipment.",
            ),
            SettingsField(
                name="pickup_type",
                label="Pickup",
                field_type=FieldType.SELECT,
                choices=["courier", "self"],
                default="courier",
                help_text="courier: the courier collects the parcel at the first available slot; self: you drop it off.",
            ),
            SettingsField(
                name="awb_wait_seconds",
                label="Seconds to wait for the AWB",
                field_type=FieldType.INT,
                default=30,
                help_text="eColet books the courier asynchronously; how long to poll for the AWB number.",
            ),
        ],
    ),
    capabilities=[CourierPort],
    rate_limit=RateLimitConfig(requests_per_second=1.5, burst=10),  # x-ratelimit-limit: 100 (per minute)
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 422],
    ),
)
