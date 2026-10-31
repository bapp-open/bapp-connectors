"""
Meta provider manifest — one Meta login reaching every Facebook Page the user
manages and the Instagram Business accounts linked to them.

Uses the Facebook Graph API v19.0. The connection stores a long-lived *user*
token; per-destination Page tokens come from ``list_destinations``.
"""

from bapp_connectors.core.capabilities import OAuthCapability, SocialDestinationsCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="meta",
    family=ProviderFamily.SOCIAL,
    display_name="Meta (Facebook + Instagram)",
    description=(
        "One Meta login that publishes to every Facebook Page the user manages and the "
        "Instagram Business accounts linked to them."
    ),
    base_url="https://graph.facebook.com/v19.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="app_id",
                label="App ID",
                required=False,
                help_text="Meta app ID, filled in by the platform.",
            ),
            CredentialField(
                name="app_secret",
                label="App Secret",
                sensitive=True,
                required=False,
                help_text="Meta app secret, filled in by the platform.",
            ),
            CredentialField(
                name="token",
                label="User Access Token",
                sensitive=True,
                required=False,
                help_text="Long-lived Meta user access token, obtained through the OAuth flow.",
            ),
        ],
        oauth=OAuthConfig(
            display_name="Conectează cu Meta",
            scopes=[
                "pages_show_list",
                "pages_read_engagement",
                "pages_manage_posts",
                "read_insights",
                "business_management",
                "instagram_basic",
                "instagram_content_publish",
                "catalog_management",
                "instagram_shopping_tag_products",
            ],
        ),
    ),
    capabilities=[OAuthCapability, SocialDestinationsCapability],
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
