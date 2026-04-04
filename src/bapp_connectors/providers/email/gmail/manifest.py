"""
Gmail email provider manifest — declares capabilities, auth, and configuration.
"""

from bapp_connectors.core.capabilities import InboxCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="gmail",
    family=ProviderFamily.EMAIL,
    display_name="Gmail",
    description="Gmail API integration for sending and reading email messages.",
    base_url="https://gmail.googleapis.com/gmail/v1/users/me/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(
                name="access_token",
                label="Access Token",
                sensitive=True,
                help_text="OAuth2 access token. Token refresh is handled externally.",
            ),
            CredentialField(
                name="from_email",
                label="From Email",
                sensitive=False,
                required=False,
                help_text="Defaults to authenticated user's email.",
            ),
        ],
    ),
    capabilities=[EmailPort, InboxCapability],
    rate_limit=RateLimitConfig(
        requests_per_second=5,
        burst=10,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[500, 502, 503],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
