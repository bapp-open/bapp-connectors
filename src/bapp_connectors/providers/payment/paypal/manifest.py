"""
PayPal payment provider manifest.

PayPal is a global payment platform supporting checkout via REST API
with OAuth2 authentication and webhook notifications.
"""

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
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

PAYPAL_LIVE_URL = "https://api.paypal.com"
PAYPAL_SANDBOX_URL = "https://api.sandbox.paypal.com"

manifest = ProviderManifest(
    name="paypal",
    family=ProviderFamily.PAYMENT,
    display_name="PayPal",
    description="PayPal — global payment platform with REST API checkout and OAuth2 auth.",
    base_url=PAYPAL_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="client_id", label="Client ID", sensitive=True),
            CredentialField(name="app_secret", label="App Secret", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="sandbox",
                label="Sandbox Mode",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Use PayPal sandbox environment for testing.",
            ),
        ],
    ),
    capabilities=[
        PaymentPort,
        WebhookCapability,
        FinancialCapability,
    ],
    rate_limit=RateLimitConfig(requests_per_second=30, burst=50),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method=None,  # PayPal uses its own verification API
        signature_header="",
        events=[
            "CHECKOUT.ORDER.APPROVED",
            "PAYMENT.CAPTURE.COMPLETED",
            "PAYMENT.CAPTURE.DENIED",
        ],
    ),
)
