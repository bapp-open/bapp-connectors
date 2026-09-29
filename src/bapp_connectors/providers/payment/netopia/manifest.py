"""
Netopia provider manifest — declares capabilities, auth, rate limits, and webhook config.
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

# secure.netopia-payments.com is the marketing site (302 to netopia-payments.com);
# the live v2 API is still served from the mobilPay host.
NETOPIA_LIVE_URL = "https://secure.mobilpay.ro/pay/"
NETOPIA_SANDBOX_URL = "https://secure.sandbox.netopia-payments.com/"

manifest = ProviderManifest(
    name="netopia",
    family=ProviderFamily.PAYMENT,
    display_name="Netopia",
    description="Netopia Payments — Romanian payment gateway for online card payments, BNPL, and Apple Pay.",
    base_url=NETOPIA_LIVE_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="api_key",
                label="API Key",
                sensitive=True,
                help_text="Netopia API key for authentication.",
            ),
            CredentialField(
                name="pos_signature",
                label="POS Signature",
                sensitive=True,
                help_text="Netopia POS signature identifier.",
            ),
            CredentialField(
                name="sandbox",
                label="Sandbox Mode",
                sensitive=False,
                required=False,
                default="true",
                help_text="Set to 'true' for sandbox/test mode, 'false' for live.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="notify_url",
                label="Notification URL",
                field_type=FieldType.STR,
                required=False,
                help_text="URL where Netopia sends payment notifications (IPN).",
            ),
            SettingsField(
                name="redirect_url",
                label="Redirect URL",
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
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        # RS512 JWT in Verification-Token, checked by the adapter's verify_webhook
        # against Netopia's published key; the generic verifier rejects it.
        signature_method="netopia-jwt",
        signature_header="Verification-Token",
        events=["payment.confirmed", "payment.pending", "payment.cancelled", "payment.credit"],
    ),
)
