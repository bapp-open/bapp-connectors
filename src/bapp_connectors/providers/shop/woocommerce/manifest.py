"""
WooCommerce provider manifest — declares capabilities, auth, rate limits, and webhook config.
"""

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    BulkUpsertCapability,
    CategoryManagementCapability,
    OAuthCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    RelatedProductCapability,
    SettingsDetectionCapability,
    VariantManagementCapability,
    WebhookCapability,
)
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
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
    allow_multiple=True,
    display_name="WooCommerce",
    description="WooCommerce store integration for orders, products, and inventory management.",
    base_url="https://placeholder.local/wp-json/wc/v3/",  # overridden dynamically from credentials
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="consumer_key", label="Consumer Key", sensitive=True, required=False),
            CredentialField(name="consumer_secret", label="Consumer Secret", sensitive=True, required=False),
            CredentialField(name="domain", label="Store Domain", sensitive=False, help_text="e.g. https://myshop.com", role="endpoint"),
            CredentialField(
                name="verify_ssl",
                label="Verify SSL",
                sensitive=False,
                required=False,
                default="true",
                help_text="Set to 'false' to disable SSL verification",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="domain", label="Store Domain", sensitive=False, help_text="e.g. https://myshop.com", role="endpoint"),
            ],
            scopes=["read_write"],
            display_name="Connect with WooCommerce",
        ),
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
            SettingsField(
                name="batch_size", label="Products per batch", field_type=FieldType.INT, default=20,
                help_text="How many products are sent in one /products/batch call (max 100). Smaller batches are gentler on the WordPress server, especially when images are included.",
            ),
            SettingsField(
                name="pause_seconds", label="Pause between batches (s)", field_type=FieldType.INT, default=2,
                help_text="Seconds to wait between consecutive batches so the store keeps serving customers.",
            ),
            SettingsField(
                name="publish_status", label="Status for new products", field_type=FieldType.SELECT,
                choices=["publish", "draft"], default="publish",
                help_text="Newly created products are published immediately or left as drafts for review.",
            ),
            SettingsField(
                name="sync_images", label="Sync product images", field_type=FieldType.BOOL, default=True,
                help_text="Send product photos to the store (WordPress downloads each image; disable for a faster first sync).",
            ),
        ],
    ),
    capabilities=[
        ShopPort,
        BulkUpdateCapability,
        BulkUpsertCapability,
        CategoryManagementCapability,
        AttributeManagementCapability,
        OAuthCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        ProductLookupCapability,
        RelatedProductCapability,
        SettingsDetectionCapability,
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
        signature_method="hmac-sha256",
        signature_header="X-WC-Webhook-Signature",
        events=["order.created", "order.updated", "product.created"],
    ),
)
