"""
Facebook/Meta Ads provider manifest — declares capabilities, auth, rate limits.

Uses the Meta Marketing API v19.0 (https://developers.facebook.com/docs/marketing-apis/).
"""

from bapp_connectors.core.capabilities import CreativeUploadCapability, OAuthCapability
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
    name="facebook",
    family=ProviderFamily.ADS,
    display_name="Facebook Ads",
    description="Meta Marketing API integration for managing campaigns, ad sets, ads, and performance insights.",
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
                    "Marketing API access token with the ads_management scope. "
                    "Optional when connecting via the OAuth flow."
                ),
            ),
            CredentialField(
                name="ad_account_id",
                label="Ad Account Id",
                help_text="Numeric ad account ID, without the act_ prefix.",
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
            scopes=["ads_management", "ads_read", "business_management"],
            display_name="Connect with Facebook",
        ),
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_optimization_goal",
                label="Default Optimization Goal",
                field_type=FieldType.SELECT,
                choices=["REACH", "IMPRESSIONS", "LINK_CLICKS", "OFFSITE_CONVERSIONS", "VIDEO_VIEWS"],
                default="LINK_CLICKS",
                help_text="Optimization goal applied to newly created ad sets.",
            ),
            SettingsField(
                name="default_billing_event",
                label="Default Billing Event",
                field_type=FieldType.SELECT,
                choices=["IMPRESSIONS", "LINK_CLICKS"],
                default="IMPRESSIONS",
                help_text="Billing event applied to newly created ad sets.",
            ),
            SettingsField(
                name="page_id",
                label="Facebook Page ID",
                field_type=FieldType.STR,
                required=False,
                help_text="Facebook Page ID that creatives publish as; required for create_creative.",
            ),
        ],
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
