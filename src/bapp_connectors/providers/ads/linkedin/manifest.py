"""
LinkedIn Ads provider manifest — declares capabilities, auth, rate limits.

Uses the LinkedIn Marketing API (https://learn.microsoft.com/en-us/linkedin/marketing/),
versioned via the LinkedIn-Version header (see the linkedin_version setting).
"""

from bapp_connectors.core.capabilities import OAuthCapability
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
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="linkedin",
    family=ProviderFamily.ADS,
    display_name="LinkedIn Ads",
    description=(
        "LinkedIn Marketing API integration for managing campaign groups, campaigns, "
        "creatives, and performance analytics."
    ),
    base_url="https://api.linkedin.com/rest/",
    auth=AuthConfig(
        # CUSTOM: Bearer token plus the Restli protocol / LinkedIn-Version headers,
        # built per call by LinkedInAdsClient.
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text=(
                    "OAuth2 access token with the rw_ads and r_ads_reporting scopes. "
                    "Optional when connecting via the OAuth flow."
                ),
            ),
            CredentialField(
                name="ad_account_id",
                label="Ad Account Id",
                help_text="Numeric sponsored ad account ID (the tail of urn:li:sponsoredAccount:*).",
            ),
            CredentialField(
                name="client_id",
                label="Client ID",
                required=False,
                help_text="LinkedIn app client ID, used for the OAuth authorization flow.",
            ),
            CredentialField(
                name="client_secret",
                label="Client Secret",
                sensitive=True,
                required=False,
                help_text="LinkedIn app client secret, used for the OAuth authorization flow.",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="client_id", label="Client ID"),
                CredentialField(name="client_secret", label="Client Secret", sensitive=True),
            ],
            scopes=["rw_ads", "r_ads_reporting"],
            display_name="Connect with LinkedIn Ads",
        ),
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="linkedin_version",
                label="LinkedIn API Version",
                field_type=FieldType.STR,
                default="202405",
                help_text="Value of the LinkedIn-Version header (YYYYMM).",
            ),
        ],
    ),
    # No CreativeUploadCapability: LinkedIn creatives reference organic posts
    # (a post URN goes into content.reference) instead of uploaded ad media.
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
