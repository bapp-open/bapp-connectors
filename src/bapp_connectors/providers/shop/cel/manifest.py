"""
CEL.ro provider manifest — declares capabilities, auth, rate limits, and webhook config.
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    WebhookConfig,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="cel",
    family=ProviderFamily.SHOP,
    display_name="CEL.ro",
    description="CEL.ro marketplace integration for orders, products, and inventory management.",
    base_url="https://api-mp.cel.ro/market_api/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,  # CEL uses login endpoint to obtain a bearer token
        required_fields=[
            CredentialField(name="username", label="API Username", sensitive=False),
            CredentialField(name="password", label="API Password", sensitive=True),
            CredentialField(
                name="country",
                label="Country Code",
                sensitive=False,
                default="RO",
                required=False,
                choices=["RO"],
            ),
        ],
    ),
    capabilities=[
        ShopPort,
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
    webhooks=WebhookConfig(
        supported=False,
    ),
)
