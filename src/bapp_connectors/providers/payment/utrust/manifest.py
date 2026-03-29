"""
Utrust payment provider manifest.

Utrust is a cryptocurrency/fiat payment gateway supporting
checkout via REST API with HMAC-SHA256 webhook verification.
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

UTRUST_LIVE_URL = "https://merchants.api.utrust.com/api"
UTRUST_SANDBOX_URL = "https://merchants.api.sandbox-utrust.com/api"

manifest = ProviderManifest(
    name="utrust",
    family=ProviderFamily.PAYMENT,
    display_name="Utrust",
    description="Utrust — cryptocurrency and fiat payment gateway with REST API.",
    base_url=UTRUST_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="api_key", label="API Key", sensitive=True),
            CredentialField(
                name="webhook_secret",
                label="Webhook Secret",
                sensitive=True,
                help_text="Secret for HMAC-SHA256 webhook signature verification.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="sandbox",
                label="Sandbox Mode",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Use Utrust sandbox environment for testing.",
            ),
        ],
    ),
    capabilities=[
        PaymentPort,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(requests_per_second=10, burst=20),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",
        signature_header="",  # Signature is in the JSON payload body
        events=["ORDER.PAYMENT.RECEIVED", "ORDER.PAYMENT.CANCELLED"],
    ),
)
