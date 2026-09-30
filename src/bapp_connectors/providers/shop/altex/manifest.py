"""
Altex Marketplace provider manifest — seller API v2.0 (https://marketplace.altex.ro/v2.0).

Source: the Swagger 2.0 spec embedded in https://marketplace.altex.ro/api_doc. Keys are
issued by the Altex Marketplace team (marketplace@altex.ro). Staging (mkp-stage.altex.ro)
is IP-allowlisted.
"""

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

ALTEX_LIVE_URL = "https://marketplace.altex.ro/v2.0/"
ALTEX_STAGING_URL = "https://mkp-stage.altex.ro/v2.0/"

manifest = ProviderManifest(
    name="altex",
    family=ProviderFamily.SHOP,
    display_name="Altex Marketplace",
    description="Altex Marketplace — orders, offers (price & stock), invoices and AWBs.",
    base_url=ALTEX_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="public_key", label="Public key"),
            CredentialField(name="private_key", label="Private key", sensitive=True),
            CredentialField(
                name="staging",
                label="Staging",
                required=False,
                default="false",
                help_text="Use mkp-stage.altex.ro (IP-allowlisted by Altex).",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="order_days",
                label="Days of orders to read",
                field_type=FieldType.INT,
                default=7,
                help_text="Window for listing orders when no start date is given (the API filters by order date).",
            ),
        ],
    ),
    capabilities=[ShopPort, ReturnsCapability],
    rate_limit=RateLimitConfig(requests_per_second=2, burst=5),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 409],
    ),
)
