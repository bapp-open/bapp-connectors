"""
PrestaShop provider manifest — declares capabilities, auth, rate limits, and webhook config.
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
    name="prestashop",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="PrestaShop",
    description="PrestaShop webservice integration for orders, products, categories, and inventory management.",
    base_url="https://placeholder.prestashop.com/api/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="domain", label="Shop Domain (e.g. https://myshop.com)", sensitive=False),
            CredentialField(name="token", label="API Key", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="prices_include_vat",
                label="Store Prices Include VAT",
                field_type=FieldType.BOOL,
                default=True,
                help_text="Whether PrestaShop prices include tax (tax_incl fields).",
            ),
            SettingsField(
                name="vat_rate",
                label="VAT Rate",
                field_type=FieldType.STR,
                default="0.19",
                help_text="VAT rate as decimal (e.g., 0.19 for 19%).",
            ),
        ],
    ),
    capabilities=[
        ShopPort,
        BulkUpdateCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        CategoryManagementCapability,
        AttributeManagementCapability,
        VariantManagementCapability,
        WebhookCapability,
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
