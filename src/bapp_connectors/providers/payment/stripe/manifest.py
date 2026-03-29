"""
Stripe provider manifest — declares capabilities, auth, rate limits, and webhook config.
"""

from bapp_connectors.core.capabilities import SavedPaymentCapability, SubscriptionCapability, WebhookCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    WebhookConfig,
)
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="stripe",
    family=ProviderFamily.PAYMENT,
    display_name="Stripe",
    description="Stripe payment processing — checkout sessions, payment intents, refunds, subscriptions, and saved cards.",
    base_url="https://api.stripe.com/v1/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="secret_key",
                label="Secret Key",
                sensitive=True,
                help_text="Stripe secret key (sk_live_... or sk_test_...)",
            ),
        ],
    ),
    capabilities=[
        PaymentPort,
        WebhookCapability,
        SubscriptionCapability,
        SavedPaymentCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=25,
        burst=50,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",
        signature_header="Stripe-Signature",
        events=[
            "checkout.session.completed",
            "payment_intent.succeeded",
            "payment_intent.payment_failed",
            "charge.refunded",
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "invoice.payment_succeeded",
            "invoice.payment_failed",
        ],
    ),
)
