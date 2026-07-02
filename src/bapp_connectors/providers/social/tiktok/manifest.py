"""
TikTok Display API provider manifest — declares capabilities, auth, rate limits.

Uses TikTok Display API v2 (https://developers.tiktok.com/doc/display-api-get-started).
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="tiktok",
    family=ProviderFamily.SOCIAL,
    display_name="TikTok",
    description="TikTok Display API v2 integration for account profile, videos, and universal statistics.",
    base_url="https://open.tiktokapis.com/v2/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="token",
                label="Access Token",
                sensitive=True,
                help_text=(
                    "TikTok Login Kit OAuth user access token with scopes "
                    "user.info.basic, user.info.profile, user.info.stats, video.list."
                ),
            ),
        ],
    ),
    capabilities=[
        SocialPort,
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
