"""
Company Store provider manifest: capabilities, credentials, settings, rate limits, webhook config.
"""

from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    VolumePricingCapability,
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
from bapp_connectors.core.types import AuthStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="bapp_store",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="Company Store (BAPP)",
    description="BAPP Company Store storefront: catalog push with volume pricing, order pull, order webhooks.",
    base_url="https://store.bapp.ro/api/",  # fixed host: the bearer token identifies the tenant, not the domain
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            # arrives from the approval flow, never typed, so the adapter must build without it
            CredentialField(name="token", label="Sync Token", sensitive=True, required=False, help_text="Store API token scoped to the sync app"),
        ],
        # empty on purpose: the add dialog shows only a provider's OAuth credential
        # fields, so declaring none is what makes it ask for the display name alone.
        # The token arrives from the approval flow, not from a form.
        # note: the dialog's non-OAuth fallback path also renders nothing here only
        # because "token" is sensitive=True; flipping that would resurface the field.
        oauth=OAuthConfig(display_name="Company Store (BAPP)"),
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
