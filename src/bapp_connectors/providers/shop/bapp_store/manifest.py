"""
Company Store provider manifest: capabilities, credentials, settings, rate limits, webhook config.
"""

from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.volume_pricing import VolumePricingCapability
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
from bapp_connectors.core.types import AuthStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="bapp_store",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="Company Store (BAPP)",
    description="BAPP Company Store storefront: catalog push with volume pricing, order pull, order webhooks.",
    base_url="https://placeholder.local/api/",  # replaced by the store_url credential in the client
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="store_url", label="Store URL", sensitive=False, help_text="Internal store host, e.g. https://acme-st.sites.bapp.ro", role="endpoint"),
            CredentialField(name="token", label="Sync Token", sensitive=True, help_text="Store API token scoped to the sync app"),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(name="prices_include_vat", label="Store Prices Include VAT", field_type=FieldType.BOOL, default=True, help_text="Company Store displays gross prices; leave on unless the store is configured net."),
            SettingsField(name="vat_rate", label="VAT Rate", field_type=FieldType.STR, default="0.21", help_text="VAT rate as a decimal (0.21 for 21%). Used to convert between net and gross prices."),
            SettingsField(name="batch_size", label="Products per batch", field_type=FieldType.INT, default=100, help_text="Products per CatalogSyncTask call (the store accepts at most 100)."),
            SettingsField(name="pause_seconds", label="Pause between batches (s)", field_type=FieldType.INT, default=1, help_text="Seconds to wait between consecutive batches."),
            SettingsField(name="publish_status", label="Status for new products", field_type=FieldType.SELECT, choices=["publish", "draft"], default="publish", help_text="New products are visible immediately or created inactive for review."),
            SettingsField(name="sync_images", label="Sync product images", field_type=FieldType.BOOL, default=True, help_text="Send photo URLs to the store (the store stores URLs, it does not download them)."),
        ],
    ),
    capabilities=[
        ShopPort,
        BulkUpsertCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        ProductLookupCapability,
        CategoryManagementCapability,
        VolumePricingCapability,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(requests_per_second=10, burst=10),
    retry=RetryConfig(),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",
        signature_header="X-BappStore-Signature",
        events=["order.created", "order.updated"],
    ),
)
