"""
Shopify Admin REST API provider manifest.
"""

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    VariantManagementCapability,
    WebhookCapability,
)
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
    WebhookConfig,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="shopify",
    family=ProviderFamily.SHOP,
    display_name="Shopify",
    description="Shopify Admin REST API integration for orders, products, variants, and inventory management.",
    base_url="https://placeholder.myshopify.com/admin/api/2024-01/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="store_domain", label="Store Domain (e.g. myshop.myshopify.com)", sensitive=False),
            CredentialField(name="access_token", label="Admin API Access Token", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="api_version",
                label="API Version",
                field_type=FieldType.STR,
                default="2024-01",
                help_text="Shopify API version (e.g., 2024-01).",
            ),
            SettingsField(
                name="prices_include_vat",
                label="Prices Include VAT",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Whether Shopify prices include tax.",
            ),
            SettingsField(
                name="vat_rate",
                label="VAT Rate",
                field_type=FieldType.STR,
                default="0.19",
            ),
        ],
    ),
    capabilities=[
        ShopPort,
        BulkUpdateCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        VariantManagementCapability,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=4,  # Shopify: 2 requests/second for standard, 4 for Plus
        burst=10,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 422],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",
        signature_header="X-Shopify-Hmac-Sha256",
        events=["orders/create", "orders/updated", "products/create", "products/update"],
    ),
)
