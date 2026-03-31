"""
Facebook Messenger provider manifest — declares capabilities, auth, rate limits, and webhook config.

Uses Meta's Send API via the Graph API (/{page_id}/messages).
"""

from bapp_connectors.core.capabilities import RichMessagingCapability, WebhookCapability
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
    name="messenger",
    family=ProviderFamily.MESSAGING,
    display_name="Facebook Messenger",
    description="Facebook Messenger integration via Meta's Send API for messages, media, templates, and webhooks.",
    base_url="https://graph.facebook.com/v21.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="page_access_token",
                label="Page Access Token",
                sensitive=True,
                help_text="Long-lived Page access token from Meta developer portal.",
            ),
            CredentialField(
                name="page_id",
                label="Page ID",
                sensitive=False,
                help_text="Facebook Page ID.",
            ),
            CredentialField(
                name="app_secret",
                label="App Secret",
                sensitive=True,
                required=False,
                help_text="Meta App Secret — used to verify webhook signatures (X-Hub-Signature-256).",
            ),
            CredentialField(
                name="webhook_verify_token",
                label="Webhook Verify Token",
                sensitive=True,
                required=False,
                help_text="Custom token for Meta's webhook URL verification challenge.",
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
                help_text="Meta Graph API version.",
            ),
        ],
    ),
    capabilities=[
        MessagingPort,
        RichMessagingCapability,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=200,
        burst=200,
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
        events=["messages", "messaging_postbacks", "message_deliveries", "message_reads"],
    ),
)
