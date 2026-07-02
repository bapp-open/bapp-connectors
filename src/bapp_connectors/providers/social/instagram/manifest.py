"""
Instagram social provider manifest — declares capabilities, auth, rate limits.

Uses the Instagram Graph API via graph.facebook.com v19.0
(https://developers.facebook.com/docs/instagram-api). Covers an Instagram
*Business/Creator* account: profile, published media, media/account insights,
and URL-based content publishing (images and Reels).
"""

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="instagram",
    family=ProviderFamily.SOCIAL,
    display_name="Instagram",
    description=(
        "Instagram Graph API integration for a Business/Creator account: profile, media "
        "(incl. Reels), insights, and URL-based publishing."
    ),
    base_url="https://graph.facebook.com/v19.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text=(
                    "Long-lived Page/user access token with instagram_basic and "
                    "instagram_manage_insights permissions; instagram_content_publish is required "
                    "for publishing. Optional when connecting via the OAuth flow (obtained "
                    "afterwards via list_instagram_accounts)."
                ),
            ),
            CredentialField(
                name="ig_user_id",
                label="Instagram Business Account ID",
                help_text="Numeric ID of the Instagram Business/Creator account (not the username).",
            ),
            CredentialField(
                name="app_id",
                label="App ID",
                required=False,
                help_text="Meta app ID, used for the OAuth authorization flow.",
            ),
            CredentialField(
                name="app_secret",
                label="App Secret",
                sensitive=True,
                required=False,
                help_text="Meta app secret, used for the OAuth authorization flow.",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="app_id", label="App ID"),
                CredentialField(name="app_secret", label="App Secret", sensitive=True),
            ],
            scopes=["instagram_basic", "instagram_content_publish", "instagram_manage_insights", "pages_show_list"],
            display_name="Connect with Instagram",
        ),
    ),
    capabilities=[
        SocialPort,
        SocialPublishCapability,
        OAuthCapability,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=10,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
