"""
MobilPay (Netopia legacy) payment provider manifest.

MobilPay uses RSA+ARC4 encrypted XML for payment requests and IPN responses.
This is the legacy Netopia card payment interface (pre-REST API).
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

MOBILPAY_LIVE_URL = "https://secure.mobilpay.ro"
MOBILPAY_SANDBOX_URL = "http://sandboxsecure.mobilpay.ro"

manifest = ProviderManifest(
    name="mobilpay",
    family=ProviderFamily.PAYMENT,
    display_name="MobilPay",
    description="MobilPay (Netopia legacy) — Romanian card payment gateway with RSA-encrypted XML.",
    base_url=MOBILPAY_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="client_key", label="Merchant Signature", sensitive=False,
                            help_text="Merchant signature/key from Netopia dashboard."),
            CredentialField(name="public_cert", label="Public Certificate (PEM)", sensitive=False,
                            help_text="X509 public certificate in PEM format for encrypting requests."),
            CredentialField(name="private_key", label="Private Key (PEM)", sensitive=True,
                            help_text="RSA private key in PEM format for decrypting IPN responses."),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="sandbox",
                label="Sandbox Mode",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Use MobilPay sandbox environment for testing.",
            ),
        ],
    ),
    capabilities=[
        PaymentPort,
        WebhookCapability,
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
        signature_method=None,  # RSA-encrypted XML, not HMAC
        signature_header="",
        events=["payment.confirmed", "payment.failed"],
    ),
)
