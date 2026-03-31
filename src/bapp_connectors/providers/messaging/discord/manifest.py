"""
Discord Bot API provider manifest — declares capabilities, auth, rate limits, and webhook config.

Uses the Discord REST API v10 (https://discord.com/api/v10/).
Receives events via Gateway websocket or interaction webhooks.
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
    name="discord",
    family=ProviderFamily.MESSAGING,
    display_name="Discord",
    description="Discord Bot API integration for sending messages, embeds, media, and receiving interaction webhooks.",
    base_url="https://discord.com/api/v10/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="bot_token",
                label="Bot Token",
                sensitive=True,
                help_text="Discord bot token from the Developer Portal (Bot > Token).",
            ),
            CredentialField(
                name="application_id",
                label="Application ID",
                sensitive=False,
                help_text="Discord application ID from the Developer Portal.",
            ),
            CredentialField(
                name="public_key",
                label="Public Key",
                sensitive=False,
                required=False,
                help_text="Ed25519 public key for verifying interaction webhook signatures.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_channel_id",
                label="Default Channel ID",
                field_type=FieldType.STR,
                required=False,
                help_text="Default channel ID for sending messages.",
            ),
        ],
    ),
    capabilities=[
        MessagingPort,
        RichMessagingCapability,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=50,
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
        signature_method=None,
        signature_header="X-Signature-Ed25519",
        events=["MESSAGE_CREATE", "INTERACTION_CREATE"],
    ),
)
