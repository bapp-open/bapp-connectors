"""
Google Ads provider manifest — declares capabilities, auth, rate limits.

Uses the Google Ads REST API v17 (https://developers.google.com/google-ads/api/rest/overview).
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
    name="google",
    family=ProviderFamily.ADS,
    display_name="Google Ads",
    description="Google Ads REST API v17 integration for campaigns, ad groups, responsive search ads, and performance reporting.",
    base_url="https://googleads.googleapis.com/v17/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="developer_token",
                label="Developer Token",
                sensitive=True,
                help_text="Google Ads API developer token from the API Center.",
            ),
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                help_text="OAuth2 access token with https://www.googleapis.com/auth/adwords scope.",
            ),
            CredentialField(
                name="customer_id",
                label="Customer ID",
                help_text="10-digit customer ID, dashes allowed (e.g. 123-456-7890).",
            ),
            CredentialField(
                name="login_customer_id",
                label="Login Customer ID",
                required=False,
                help_text="Manager/MCC account ID when accessing a client account.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="currency",
                label="Currency",
                field_type=FieldType.STR,
                default="USD",
                help_text="Google reports cost in the account currency; used to label spend.",
            ),
        ],
    ),
    capabilities=[
        AdsPort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=5,
        burst=5,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
