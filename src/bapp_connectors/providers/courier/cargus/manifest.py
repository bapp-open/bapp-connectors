"""
Cargus provider manifest — UrgentOnlineAPI (https://urgentcargus.azure-api.net/api).

Source: the OpenAPI export of Cargus' Azure API Management portal
(urgentcargus.developer.azure-api.net, API "UrgentOnlineAPI"), the official
DocumentationAPIV3 PDF and the official Cargus WooCommerce plugin.
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

CARGUS_LIVE_URL = "https://urgentcargus.azure-api.net/api/"
CARGUS_TEST_URL = "https://urgentcargusapitest.azure-api.net/api/"

manifest = ProviderManifest(
    name="cargus",
    family=ProviderFamily.COURIER,
    display_name="Cargus",
    description="Cargus — AWB generation, labels, tracking and cancellation (UrgentOnline API).",
    base_url=CARGUS_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="subscription_key",
                label="API subscription key",
                sensitive=True,
                help_text="Primary key of the UrgentOnlineAPI subscription (urgentcargus.developer.azure-api.net).",
            ),
            CredentialField(name="username", label="WebExpress username"),
            CredentialField(name="password", label="WebExpress password", sensitive=True),
            CredentialField(
                name="pickup_location_id",
                label="Pickup location ID",
                required=False,
                help_text="Sender pickup point (LocationId). Empty: the first active point of the user.",
            ),
            CredentialField(
                name="test",
                label="Test environment",
                required=False,
                default="false",
                help_text="Use urgentcargusapitest.azure-api.net (needs a test subscription).",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="service_id",
                label="Service ID",
                field_type=FieldType.INT,
                default=34,
                help_text="34 Economic Standard (<=31 kg), 35 Standard Plus (31-50 kg), 36 Palet, 39 Multipiece. "
                "Lockers (Ship & Go) always use 38.",
            ),
            SettingsField(
                name="cod_to_bank_account",
                label="Cash on delivery to bank account",
                field_type=FieldType.BOOL,
                default=True,
                help_text="Collected cash wired to the account (BankRepayment) instead of returned in an envelope "
                "(CashRepayment).",
            ),
            SettingsField(
                name="payer",
                label="Shipping paid by",
                field_type=FieldType.SELECT,
                choices=["sender", "recipient"],
                default="sender",
            ),
            SettingsField(
                name="label_format",
                label="Label format",
                field_type=FieldType.SELECT,
                choices=["A4", "label"],
                default="A4",
                help_text="label = 10x14 cm.",
            ),
        ],
    ),
    capabilities=[CourierPort],
    rate_limit=RateLimitConfig(requests_per_second=3, burst=6),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 409],
    ),
)
