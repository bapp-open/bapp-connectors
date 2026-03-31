"""
Matrix messaging provider manifest — declares capabilities, auth, rate limits, and webhook config.

Uses the Matrix Client-Server API (/_matrix/client/v3/).
Webhooks via the Application Service API (homeserver POSTs events to a registered URL).
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
    name="matrix",
    family=ProviderFamily.MESSAGING,
    display_name="Matrix",
    description="Matrix protocol integration via Element/Synapse for messaging, media, and webhooks.",
    base_url="https://matrix.example.com/_matrix/client/v3/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                help_text="Matrix access token (from login or bot account).",
            ),
            CredentialField(
                name="homeserver_url",
                label="Homeserver URL",
                sensitive=False,
                help_text="Matrix homeserver base URL (e.g. https://matrix.example.com).",
            ),
            CredentialField(
                name="appservice_token",
                label="Appservice Token",
                sensitive=True,
                required=False,
                help_text="HS token for verifying incoming appservice webhook requests.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_room_id",
                label="Default Room ID",
                field_type=FieldType.STR,
                required=False,
                help_text="Default room ID for sending messages (e.g. !abc123:example.com).",
            ),
        ],
    ),
    capabilities=[
        MessagingPort,
        RichMessagingCapability,
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
        signature_method=None,
        signature_header="",
        events=["m.room.message", "m.room.member"],
    ),
)
