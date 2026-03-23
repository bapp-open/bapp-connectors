"""
WooCommerce provider manifest — declares capabilities, auth, rate limits, and webhook config.
"""

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
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
    name="woocommerce",
    family=ProviderFamily.SHOP,
    display_name="WooCommerce",
    description="WooCommerce store integration for orders, products, and inventory management.",
    base_url="https://placeholder.local/wp-json/wc/v3/",  # overridden dynamically from credentials
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="consumer_key", label="Consumer Key", sensitive=True),
            CredentialField(name="consumer_secret", label="Consumer Secret", sensitive=True),
            CredentialField(name="domain", label="Store Domain", sensitive=False, help_text="e.g. https://myshop.com"),
            CredentialField(
                name="verify_ssl",
                label="Verify SSL",
                sensitive=False,
                required=False,
                default="true",
                help_text="Set to 'false' to disable SSL verification",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="prices_include_vat",
                label="Store Prices Include VAT",
                field_type=FieldType.BOOL,
                default=True,
                help_text="Whether the WooCommerce store is configured to use VAT-inclusive prices (WooCommerce > Settings > Tax > Prices entered with tax).",
            ),
            SettingsField(
                name="vat_rate",
                label="VAT Rate",
                field_type=FieldType.STR,
                default="0.19",
                help_text="VAT rate as a decimal (e.g., 0.19 for 19%). Used to convert between net and gross prices.",
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
        signature_method="hmac-sha256",
        signature_header="X-WC-Webhook-Signature",
        events=["order.created", "order.updated", "product.created"],
    ),
)
