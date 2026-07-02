"""
Pinterest social provider manifest — declares capabilities, auth, rate limits.

Uses the Pinterest API v5 (https://developers.pinterest.com/docs/api/v5/).
Covers the connected Pinterest account: profile, pins, pin/account analytics,
and publishing image pins by URL.
"""

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="pinterest",
    family=ProviderFamily.SOCIAL,
    display_name="Pinterest",
    description=(
        "Pinterest API v5 integration for account profile, pins, and universal "
        "statistics via pin/account analytics, with image pin publishing by URL."
    ),
    base_url="https://api.pinterest.com/v5/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text=(
                    "Pinterest OAuth user access token with scopes user_accounts:read, "
                    "boards:read, pins:read. Publishing additionally requires pins:write. "
                    "Leave empty when connecting via OAuth."
                ),
            ),
            CredentialField(
                name="client_id",
                label="Client ID",
                required=False,
                help_text="Pinterest app client ID (needed for the OAuth flow).",
            ),
            CredentialField(
                name="client_secret",
                label="Client Secret",
                sensitive=True,
                required=False,
                help_text="Pinterest app client secret (needed for the OAuth flow).",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="client_id", label="Client ID"),
                CredentialField(name="client_secret", label="Client Secret", sensitive=True),
            ],
            scopes=[
                "user_accounts:read",
                "boards:read",
                "pins:read",
                "pins:write",
            ],
            display_name="Connect with Pinterest",
        ),
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_board_id",
                label="Default Board ID",
                field_type=FieldType.STR,
                required=False,
                help_text=(
                    "Board used by publish_post when the draft doesn't specify one "
                    "via draft.extra['board_id']."
                ),
            ),
        ],
    ),
    capabilities=[
        SocialPort,
        SocialPublishCapability,
        OAuthCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=5,
        burst=10,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
