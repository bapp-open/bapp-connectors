"""
Mailchimp Transactional (Mandrill) email provider manifest — declares capabilities, auth, and configuration.
"""

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
    name="mailchimp",
    family=ProviderFamily.EMAIL,
    display_name="Mailchimp Transactional",
    description="Mailchimp Transactional (Mandrill) email integration.",
    base_url="https://mandrillapp.com/api/1.0/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,  # API key goes in JSON body, not headers
        required_fields=[
            CredentialField(name="api_key", label="API Key", sensitive=True),
            CredentialField(name="from_email", label="Default From Email", sensitive=False),
            CredentialField(
                name="from_name",
                label="Default From Name",
                sensitive=False,
                required=False,
            ),
        ],
    ),
    capabilities=[EmailPort],
    rate_limit=RateLimitConfig(requests_per_second=10, burst=20),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
