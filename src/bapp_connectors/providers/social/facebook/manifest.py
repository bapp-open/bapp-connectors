"""
Facebook Page social provider manifest — declares capabilities, auth, rate limits.

Uses the Facebook Graph API v19.0 (https://developers.facebook.com/docs/graph-api).
Covers a Facebook *Page*: profile, published posts (including Reels as they
appear in the posts edge), and page/post insights.
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
    name="facebook",
    family=ProviderFamily.SOCIAL,
    display_name="Facebook Page",
    description="Facebook Graph API integration for a Facebook Page: profile, posts (incl. Reels), and insights.",
    base_url="https://graph.facebook.com/v19.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="token",
                label="Page Access Token",
                sensitive=True,
                help_text="Long-lived Page access token with pages_read_engagement and read_insights permissions.",
            ),
            CredentialField(
                name="page_id",
                label="Page ID",
                help_text="Numeric ID of the Facebook Page.",
            ),
        ],
    ),
    capabilities=[
        SocialPort,
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
