"""
TikTok Ads provider manifest — declares capabilities, auth, and rate limits.

Uses the TikTok Business API v1.3 (https://business-api.tiktok.com/).
"""

from bapp_connectors.core.capabilities import CreativeUploadCapability, OAuthCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="tiktok",
    family=ProviderFamily.ADS,
    display_name="TikTok Ads",
    description="TikTok Business API integration for managing campaigns, ad groups, ads, and performance reporting.",
    base_url="https://business-api.tiktok.com/open_api/v1.3/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text=(
                    "TikTok for Business access token (sent as the Access-Token header). "
                    "Leave empty when connecting via OAuth."
                ),
            ),
            CredentialField(
                name="advertiser_id",
                label="Advertiser ID",
                help_text="Numeric TikTok Ads advertiser account ID.",
            ),
            CredentialField(
                name="app_id",
                label="App ID",
                required=False,
                help_text="TikTok for Business developer app ID (needed for the OAuth flow).",
            ),
            CredentialField(
                name="app_secret",
                label="App Secret",
                sensitive=True,
                required=False,
                help_text="TikTok for Business developer app secret (needed for the OAuth flow).",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="app_id", label="App ID"),
                CredentialField(name="app_secret", label="App Secret", sensitive=True),
            ],
            # Business API scopes are configured on the developer app, not the URL.
            scopes=[],
            display_name="Connect with TikTok for Business",
        ),
    ),
    capabilities=[
        AdsPort,
        CreativeUploadCapability,
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
