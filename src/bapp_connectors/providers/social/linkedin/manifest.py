"""
LinkedIn Page social provider manifest — declares capabilities, auth, rate limits.

Uses the LinkedIn Marketing/Community Management REST APIs
(https://learn.microsoft.com/en-us/linkedin/marketing/) for an organization
(company) page: profile, published posts, share statistics, and publishing
(text and article-link posts).
"""

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
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
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="linkedin",
    family=ProviderFamily.SOCIAL,
    display_name="LinkedIn Page",
    description=(
        "LinkedIn REST API integration for an organization (company) page: profile, "
        "posts, share statistics, and publishing text/article posts."
    ),
    base_url="https://api.linkedin.com/rest/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                required=False,
                help_text=(
                    "OAuth2 member access token with the r_organization_social scope; "
                    "w_organization_social is required for publishing and "
                    "rw_organization_admin for share statistics. Optional when "
                    "connecting via the OAuth flow."
                ),
            ),
            CredentialField(
                name="organization_id",
                label="Organization ID",
                help_text="Numeric ID of the LinkedIn organization (company page).",
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
            scopes=["r_organization_social", "w_organization_social", "rw_organization_admin"],
            display_name="Connect with LinkedIn",
        ),
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="linkedin_version",
                label="LinkedIn Version",
                field_type=FieldType.STR,
                default="202405",
                help_text="Value of the LinkedIn-Version header sent on every REST API call (YYYYMM).",
            ),
        ],
    ),
    capabilities=[
        SocialPort,
        SocialPublishCapability,
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
