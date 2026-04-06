"""
Okazii provider manifest — declares capabilities, auth, rate limits, and webhook config.
"""

from __future__ import annotations

from bapp_connectors.core.capabilities import InvoiceAttachmentCapability, ShippingCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="okazii",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="Okazii",
    description="Okazii marketplace integration for orders and product management.",
    base_url="https://api.okazii.ro/v2/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(name="token", label="API Token", sensitive=True),
        ],
    ),
    capabilities=[
        ShopPort,
        InvoiceAttachmentCapability,
        ShippingCapability,
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
