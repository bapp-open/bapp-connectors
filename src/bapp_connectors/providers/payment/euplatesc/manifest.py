"""
EuPlatesc payment provider manifest.

EuPlatesc is a Romanian payment gateway supporting card payments
with form-based checkout and HMAC-MD5 IPN verification.
"""

from bapp_connectors.core.capabilities import WebhookCapability
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
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

EUPLATESC_LIVE_URL = "https://secure.euplatesc.ro/tdsprocess/tranzactd.php"
EUPLATESC_SANDBOX_URL = "https://secure.euplatesc.ro/tdsprocess/tranzactd.php"

manifest = ProviderManifest(
    name="euplatesc",
    family=ProviderFamily.PAYMENT,
    display_name="EuPlatesc",
    description="EuPlatesc — Romanian payment gateway for online card payments with recurring support.",
    base_url="https://secure.euplatesc.ro/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="merchant_id",
                label="Merchant ID",
                sensitive=False,
                help_text="EuPlatesc Merchant ID (MID).",
            ),
            CredentialField(
                name="merchant_key",
                label="Merchant Key",
                sensitive=True,
                help_text="EuPlatesc Merchant Key (hex-encoded).",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_currency",
                label="Default Currency",
                field_type=FieldType.SELECT,
                choices=["RON", "EUR", "USD"],
                default="RON",
                help_text="Default currency for payments.",
            ),
            SettingsField(
                name="notify_url",
                label="IPN Notification URL",
                field_type=FieldType.STR,
                required=False,
                help_text="URL where EuPlatesc sends payment notifications.",
            ),
            SettingsField(
                name="back_url",
                label="Back URL",
                field_type=FieldType.STR,
                required=False,
                help_text="URL where the customer is redirected after payment.",
            ),
        ],
    ),
    capabilities=[
        PaymentPort,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-md5",
        signature_header="",  # EuPlatesc includes fp_hash in POST body, not header
        events=["payment.confirmed", "payment.failed"],
    ),
)
