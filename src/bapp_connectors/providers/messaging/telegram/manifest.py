"""
Telegram Bot API provider manifest — declares capabilities, auth, rate limits.

Uses Telegram Bot API (https://core.telegram.org/bots/api).
"""

from bapp_connectors.core.capabilities import RichMessagingCapability
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
    name="telegram",
    family=ProviderFamily.MESSAGING,
    display_name="Telegram",
    description="Telegram Bot API integration for sending messages, media, stickers, locations, and interactive content.",
    base_url="https://api.telegram.org/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="bot_token",
                label="Bot Token",
                sensitive=True,
                help_text="Bot token from @BotFather (format: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11).",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="parse_mode",
                label="Default Parse Mode",
                field_type=FieldType.SELECT,
                choices=["HTML", "Markdown", "MarkdownV2"],
                default="HTML",
                help_text="Default formatting for message text.",
            ),
        ],
    ),
    capabilities=[
        MessagingPort,
        RichMessagingCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=30,
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
        signature_header="X-Telegram-Bot-Api-Secret-Token",
        events=["message", "callback_query", "edited_message"],
    ),
)
