"""
eMAG provider manifest — declares capabilities, auth, rate limits, and webhook config.
"""

from bapp_connectors.core.capabilities import BulkUpdateCapability, InvoiceAttachmentCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

# eMAG uses per-country base URLs; the default (RO) is set here.
# The adapter overrides base_url at runtime based on the "country" credential.
EMAG_BASE_URLS: dict[str, str] = {
    "RO": "https://marketplace-api.emag.ro/api-3/",
    "BG": "https://marketplace-api.emag.bg/api-3/",
    "HU": "https://marketplace-api.emag.hu/api-3/",
    "PL": "https://marketplace-api.emag.pl/api-3/",
}

manifest = ProviderManifest(
    name="emag",
    family=ProviderFamily.SHOP,
    display_name="eMAG",
    description="eMAG marketplace integration for orders, products, and inventory management.",
    base_url=EMAG_BASE_URLS["RO"],
    auth=AuthConfig(
        strategy=AuthStrategy.BASIC,
        required_fields=[
            CredentialField(name="username", label="API Username", sensitive=False),
            CredentialField(name="password", label="API Password", sensitive=True),
            CredentialField(
                name="country",
                label="Country Code",
                sensitive=False,
                default="RO",
                required=False,
                choices=["RO", "BG", "HU", "PL"],
            ),
        ],
    ),
    capabilities=[
        ShopPort,
        BulkUpdateCapability,
        InvoiceAttachmentCapability,
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
