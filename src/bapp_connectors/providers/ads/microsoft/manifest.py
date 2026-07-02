"""
Microsoft Ads (Bing Ads) provider manifest — declares capabilities, auth, rate limits.

Uses the Bing Ads API v13 Campaign Management SOAP service
(https://learn.microsoft.com/en-us/advertising/campaign-management-service/).
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
    name="microsoft",
    family=ProviderFamily.ADS,
    display_name="Microsoft Ads",
    description="Microsoft Advertising (Bing Ads) API v13 SOAP integration for campaigns, ad groups, "
    "responsive search ads, and performance reporting.",
    base_url="https://campaign.api.bingads.microsoft.com/Api/Advertiser/CampaignManagement/v13/CampaignManagementService.svc",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="developer_token",
                label="Developer Token",
                sensitive=True,
                help_text="Microsoft Advertising developer token from the Developer Portal.",
            ),
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text="Microsoft identity platform OAuth2 access token with the msads.manage scope.",
            ),
            CredentialField(
                name="customer_id",
                label="Customer ID",
                help_text="Microsoft Advertising customer (manager) ID that owns the ad account.",
            ),
            CredentialField(
                name="account_id",
                label="Account ID",
                help_text="Microsoft Advertising ad account ID (CustomerAccountId).",
            ),
            CredentialField(
                name="client_id",
                label="Client ID",
                sensitive=False,
                required=False,
                help_text="Azure AD application (client) ID for the redirect-based authorization flow.",
            ),
            CredentialField(
                name="client_secret",
                label="Client Secret",
                sensitive=True,
                required=False,
                help_text="Azure AD application client secret for the redirect-based authorization flow.",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="client_id", label="Client ID", sensitive=False),
                CredentialField(name="client_secret", label="Client Secret", sensitive=True),
            ],
            scopes=["https://ads.microsoft.com/msads.manage", "offline_access"],
            display_name="Connect with Microsoft Ads",
        ),
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="currency",
                label="Currency",
                field_type=FieldType.STR,
                default="USD",
                help_text="Microsoft reports spend in the account currency; used to label spend.",
            ),
        ],
    ),
    capabilities=[
        AdsPort,
        OAuthCapability,
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
