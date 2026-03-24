"""
LibraPay payment provider manifest.

LibraPay is a Romanian payment gateway (Libra Internet Bank) supporting
card payments with form-based checkout and HMAC-SHA1 IPN verification.
"""

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

LIBRAPAY_LIVE_URL = "https://secure.librapay.ro/pay_auth.php"
LIBRAPAY_SANDBOX_URL = "https://merchant.librapay.ro/pay_auth.php"

manifest = ProviderManifest(
    name="librapay",
    family=ProviderFamily.PAYMENT,
    display_name="LibraPay",
    description="LibraPay — Libra Internet Bank payment gateway for online card payments.",
    base_url="https://secure.librapay.ro/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="merchant", label="Merchant ID", sensitive=False),
            CredentialField(name="terminal", label="Terminal ID", sensitive=False),
            CredentialField(name="key", label="Merchant Key (hex-encoded)", sensitive=True),
            CredentialField(name="merchant_name", label="Merchant Name", sensitive=False),
            CredentialField(name="merchant_url", label="Merchant URL", sensitive=False),
            CredentialField(name="merchant_email", label="Merchant Email", sensitive=False),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="sandbox",
                label="Sandbox Mode",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Use LibraPay sandbox environment for testing.",
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
    ],
    rate_limit=RateLimitConfig(requests_per_second=10, burst=20),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha1",
        signature_header="",  # LibraPay includes P_SIGN in POST body
        events=["payment.confirmed", "payment.failed"],
    ),
)
