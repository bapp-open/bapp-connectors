"""
WhatsApp Cloud API provider manifest — declares capabilities, auth, rate limits.

Uses Meta's WhatsApp Business Cloud API (Graph API).
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
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="whatsapp",
    family=ProviderFamily.MESSAGING,
    display_name="WhatsApp",
    description="WhatsApp Business Cloud API integration for sending messages, media, templates, and interactive content.",
    base_url="https://graph.facebook.com/v21.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="token",
                label="Access Token",
                sensitive=True,
                help_text="Permanent or temporary access token from Meta developer portal.",
            ),
            CredentialField(
                name="phone_number_id",
                label="Phone Number ID",
                sensitive=False,
                help_text="Phone number ID from Meta WhatsApp Business dashboard.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="api_version",
                label="API Version",
                field_type=FieldType.STR,
                default="v21.0",
                help_text="Meta Graph API version (e.g., v21.0).",
            ),
        ],
    ),
    capabilities=[
        MessagingPort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=80,
        burst=100,
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
        signature_header="X-Hub-Signature-256",
        events=["messages", "message_status"],
    ),
)
