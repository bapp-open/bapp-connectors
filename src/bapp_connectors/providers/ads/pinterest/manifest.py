"""
Pinterest Ads provider manifest — declares capabilities, auth, and rate limits.

Uses the Pinterest API v5 (https://developers.pinterest.com/docs/api/v5/).

Pinterest has no standalone creative upload: an ad always promotes an existing
Pin, so the provider declares no CreativeUploadCapability. ``Ad.creative.id``
carries the ``pin_id`` of the Pin being promoted — create the Pin first (e.g.
via the social/pinterest provider) and pass its ID when creating ads.
"""

from bapp_connectors.core.capabilities import OAuthCapability
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
    name="pinterest",
    family=ProviderFamily.ADS,
    display_name="Pinterest Ads",
    description=(
        "Pinterest API v5 integration for managing campaigns, ad groups, ads, and performance analytics. "
        "Ads promote existing Pins (Ad.creative.id carries the pin_id), so there is no creative upload."
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
                    "Pinterest access token with the ads:read and ads:write scopes. "
                    "Optional when connecting via the OAuth flow."
                ),
            ),
            CredentialField(
                name="ad_account_id",
                label="Ad Account Id",
                help_text="Numeric Pinterest ad account ID.",
            ),
            CredentialField(
                name="client_id",
                label="Client ID",
                required=False,
                help_text="Pinterest app client ID, used for the OAuth authorization flow.",
            ),
            CredentialField(
                name="client_secret",
                label="Client Secret",
                sensitive=True,
                required=False,
                help_text="Pinterest app client secret, used for the OAuth authorization flow.",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="client_id", label="Client ID"),
                CredentialField(name="client_secret", label="Client Secret", sensitive=True),
            ],
            scopes=["ads:read", "ads:write"],
            display_name="Connect with Pinterest Ads",
        ),
    ),
    capabilities=[
        AdsPort,
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
