"""
PrestaShop provider manifest — declares capabilities, auth, rate limits, and webhook config.
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
    name="prestashop",
    family=ProviderFamily.SHOP,
    display_name="PrestaShop",
    description="PrestaShop webservice integration for orders, products, categories, and inventory management.",
    base_url="https://placeholder.prestashop.com/api/",  # Overridden per-instance from domain credential
    auth=AuthConfig(
        strategy=AuthStrategy.TOKEN,
        required_fields=[
            CredentialField(name="domain", label="Shop Domain (e.g. https://myshop.com)", sensitive=False),
            CredentialField(name="token", label="API Key", sensitive=True),
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
        supported=True,
        signature_method=None,
        events=["order.created", "order.update", "order.return"],
    ),
)
