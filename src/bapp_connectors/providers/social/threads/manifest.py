"""
Threads social provider manifest — declares capabilities, auth, rate limits.

Uses the Threads API (https://developers.facebook.com/docs/threads), Meta's
Graph-style API for the Threads platform: profile, published threads,
media/user insights, and publishing (text, image, video posts).
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
    name="threads",
    family=ProviderFamily.SOCIAL,
    display_name="Threads",
    description=(
        "Threads API integration for the connected profile: posts, media/user insights, "
        "and publishing (text, image, video)."
    ),
    base_url="https://graph.threads.net/v1.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text=(
                    "Threads user access token with threads_basic and threads_manage_insights "
                    "permissions; threads_content_publish is required for publishing. Optional "
                    "when connecting via the OAuth flow. The API addresses the token owner as "
                    "'me' — no separate user ID credential is needed."
                ),
            ),
            CredentialField(
                name="app_id",
                label="App ID",
                required=False,
                help_text="Meta app ID (Threads use case), used for the OAuth authorization flow.",
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
            scopes=["threads_basic", "threads_content_publish", "threads_manage_insights"],
            display_name="Connect with Threads",
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
