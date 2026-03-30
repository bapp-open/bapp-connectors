"""
Magento 2 / Adobe Commerce provider manifest.
"""

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
    VariantManagementCapability,
)
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

manifest = ProviderManifest(
    name="magento",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="Magento",
    description="Magento 2 / Adobe Commerce integration for orders, products, categories, and inventory management.",
    base_url="https://placeholder.magento.com/rest/V1/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="domain", label="Store URL (e.g. https://myshop.com)", sensitive=False),
            CredentialField(
                name="access_token",
                label="Integration Access Token",
                sensitive=True,
                help_text="Bearer token from Magento Admin > System > Integrations.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="store_code",
                label="Store Code",
                field_type=FieldType.STR,
                default="default",
                help_text="Magento store view code (e.g., 'default', 'en', 'ro'). Used in the API URL path.",
            ),
            SettingsField(
                name="prices_include_vat",
                label="Catalog Prices Include VAT",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Whether Magento catalog prices include tax (Stores > Config > Tax > Catalog Prices).",
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
        RelatedProductCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
