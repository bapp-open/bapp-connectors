"""Temu provider manifest (Partner Platform open API, local-to-local sellers)."""

from bapp_connectors.core.capabilities import (
    BulkUpdateCapability,
    CustomerDetailsCapability,
    FinancialCapability,
    FulfillmentCapability,
    InvoiceAttachmentCapability,
    OrderAmountCapability,
    OrderLookupCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ReturnsCapability,
    ShippingCapability,
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
from bapp_connectors.providers.shop.temu.client import ROUTERS
from bapp_connectors.providers.shop.temu.models import WebhookEventCode

#: webhook signature scheme verified by the adapter (AES-CBC body + HMAC-SHA256 over headers)
WEBHOOK_SIGNATURE_METHOD = "temu-hmac-aes"

manifest = ProviderManifest(
    name="temu",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="Temu",
    description="Temu marketplace (local seller): products, orders, shipping, invoices, settlements, returns.",
    base_url=ROUTERS["eu"],
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="app_key", label="App key", sensitive=False, colspan=12),
            CredentialField(name="app_secret", label="App secret", sensitive=True, colspan=12),
            CredentialField(name="access_token", label="Access token", sensitive=True, colspan=12,
                            help_text="Seller Center → System Management → Authorization Management → Authorize a new app."),
            CredentialField(name="region", label="Region", sensitive=False, required=False, default="eu",
                            choices=["eu", "us", "global"], colspan=6),
            CredentialField(name="mall_id", label="Mall ID", sensitive=False, required=False, role="endpoint", colspan=6,
                            help_text="Completat automat la testarea conexiunii."),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(name="fulfillment", label="Expediere", field_type=FieldType.SELECT, default="self",
                          choices=["self", "temu_label"],
                          help_text="self = AWB propriu confirmat la Temu; temu_label = etichetă cumpărată prin Temu."),
            SettingsField(name="warehouse_id", label="Depozit Temu", field_type=FieldType.STR, default="",
                          help_text="Gol = depozitul implicit al magazinului."),
            SettingsField(name="invoice_upload", label="Încărcarea facturii", field_type=FieldType.SELECT, default="nightly",
                          choices=["off", "immediate", "nightly"]),
            SettingsField(name="default_weight_g", label="Greutate implicită (g)", field_type=FieldType.INT, default=100),
            SettingsField(name="default_length_cm", label="Lungime implicită (cm)", field_type=FieldType.INT, default=10),
            SettingsField(name="default_width_cm", label="Lățime implicită (cm)", field_type=FieldType.INT, default=20),
            SettingsField(name="default_height_cm", label="Înălțime implicită (cm)", field_type=FieldType.INT, default=30),
            SettingsField(name="weight_unit", label="Unitate greutate produs", field_type=FieldType.SELECT, default="g",
                          choices=["g", "kg"]),
            SettingsField(name="size_unit", label="Unitate dimensiuni produs", field_type=FieldType.SELECT, default="cm",
                          choices=["mm", "cm"]),
            SettingsField(name="shipment_limit_day", label="Zile până la expediere", field_type=FieldType.INT,
                          default=None, required=False),
            SettingsField(name="import_orders_without_amounts", label="Importă comenzi fără sume (dezvoltare)",
                          field_type=FieldType.BOOL, default=False,
                          help_text="Doar pentru magazinul de test: comenzile fără scope-ul de sume intră cu preț 0."),
        ]
    ),
    capabilities=[
        ShopPort,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        BulkUpdateCapability,
        WebhookCapability,
        InvoiceAttachmentCapability,
        ShippingCapability,
        FulfillmentCapability,
        OrderAmountCapability,
        CustomerDetailsCapability,
        FinancialCapability,
        ReturnsCapability,
        OrderLookupCapability,
    ],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method=WEBHOOK_SIGNATURE_METHOD,
        signature_header="x-tm-signature",
        events=[code.value for code in WebhookEventCode],
    ),
)
