"""
Instagram Messaging (DM) provider manifest.

Uses Meta's Instagram Messaging API via the Graph API.
Webhook events arrive with object="instagram".
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
    name="instagram",
    family=ProviderFamily.MESSAGING,
    display_name="Instagram DM",
    description="Instagram Direct Messages via Meta's Messaging API for text, media, and story replies.",
    base_url="https://graph.facebook.com/v21.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="page_access_token",
                label="Page Access Token",
                sensitive=True,
                help_text="Page access token linked to the Instagram account (same token used for Messenger).",
            ),
            CredentialField(
                name="ig_user_id",
                label="Instagram User ID",
                sensitive=False,
                help_text="Instagram-scoped user ID (numeric). Found in Meta Business Suite or via /me?fields=instagram_business_account.",
            ),
            CredentialField(
                name="app_secret",
                label="App Secret",
                sensitive=True,
                required=False,
                help_text="Meta App Secret for webhook signature verification (X-Hub-Signature-256).",
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
        events=["messages", "messaging_postbacks", "message_reactions"],
    ),
)
