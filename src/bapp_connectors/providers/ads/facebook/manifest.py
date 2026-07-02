"""
Facebook/Meta Ads provider manifest — declares capabilities, auth, rate limits.

Uses the Meta Marketing API v19.0 (https://developers.facebook.com/docs/marketing-apis/).
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
                help_text="Marketing API access token with the ads_management scope.",
            ),
            CredentialField(
                name="ad_account_id",
                label="Ad Account Id",
                help_text="Numeric ad account ID, without the act_ prefix.",
            ),
        ],
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
        ],
    ),
    capabilities=[
        AdsPort,
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
