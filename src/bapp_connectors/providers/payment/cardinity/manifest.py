"""
Cardinity payment provider manifest.

Cardinity is a Lithuanian payment gateway supporting card payments
via hosted checkout page with HMAC-SHA256 form signature.
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

CARDINITY_CHECKOUT_URL = "https://checkout.cardinity.com"

manifest = ProviderManifest(
    name="cardinity",
    family=ProviderFamily.PAYMENT,
    display_name="Cardinity",
    description="Cardinity — hosted payment page with HMAC-SHA256 signed checkout forms.",
    base_url=CARDINITY_CHECKOUT_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="project_key", label="Project Key", sensitive=False),
            CredentialField(name="project_secret", label="Project Secret", sensitive=True),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_country",
                label="Default Country",
                field_type=FieldType.STR,
                required=False,
                default="LT",
                help_text="ISO 3166-1 alpha-2 country code for checkout.",
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
        signature_method="hmac-sha256",
        signature_header="",  # Cardinity returns status via POST form fields
        events=["payment.approved", "payment.pending", "payment.declined"],
    ),
)
