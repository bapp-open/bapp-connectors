"""
YouTube Shorts provider manifest — declares capabilities, auth, rate limits.

Uses the YouTube Data API v3 (https://developers.google.com/youtube/v3).
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="youtube",
    family=ProviderFamily.SOCIAL,
    display_name="YouTube Shorts",
    description="YouTube Data API v3 integration for reading channel info, Shorts/videos, and their statistics.",
    base_url="https://www.googleapis.com/youtube/v3/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="api_key",
                label="API Key",
                sensitive=True,
                required=False,
                help_text="Google API key for public data access.",
            ),
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text="OAuth2 access token; required for `mine=true` channel access.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="channel_id",
                label="Channel ID",
                field_type=FieldType.STR,
                required=False,
                help_text=(
                    "Channel to read; may be omitted when access_token is set — "
                    "then the authorized user's channel is used."
                ),
            ),
            SettingsField(
                name="shorts_only",
                label="Shorts Only",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Only include Shorts, i.e. videos not longer than shorts_max_seconds.",
            ),
            SettingsField(
                name="shorts_max_seconds",
                label="Shorts Max Seconds",
                field_type=FieldType.INT,
                default=180,
                help_text="Maximum duration in seconds for a video to count as a Short.",
            ),
        ],
    ),
    capabilities=[
        SocialPort,
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
)
