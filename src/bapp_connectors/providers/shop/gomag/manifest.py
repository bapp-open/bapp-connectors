"""
Gomag provider manifest — declares capabilities, auth, rate limits, and webhook config.
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
    name="gomag",
    family=ProviderFamily.SHOP,
    display_name="Gomag",
    description="Gomag e-commerce platform integration for orders, products, and inventory management.",
    base_url="https://api.gomag.ro/api/v1/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="token", label="API Key", sensitive=True),
            CredentialField(name="shop_site", label="Shop Domain", sensitive=False, help_text="e.g. myshop.gomag.ro"),
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
