"""
SMTP email provider manifest — declares capabilities, auth, and configuration.
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import MessagingPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="smtp",
    family=ProviderFamily.MESSAGING,
    display_name="SMTP Email",
    description="SMTP email integration for sending email messages.",
    base_url="smtp://localhost",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="host", label="SMTP Host", sensitive=False),
            CredentialField(name="port", label="SMTP Port", sensitive=False, default="587"),
            CredentialField(name="username", label="Username", sensitive=False),
            CredentialField(name="password", label="Password", sensitive=True),
            CredentialField(
                name="from_email",
                label="From Email",
                sensitive=False,
                required=False,
                help_text="Defaults to username if not set.",
            ),
            CredentialField(
                name="use_tls",
                label="Use TLS",
                sensitive=False,
                required=False,
                default="true",
                choices=["true", "false"],
            ),
            CredentialField(
                name="use_ssl",
                label="Use SSL",
                sensitive=False,
                required=False,
                default="false",
                choices=["true", "false"],
            ),
            CredentialField(
                name="timeout",
                label="Timeout (seconds)",
                sensitive=False,
                required=False,
                default="30",
            ),
        ],
    ),
    capabilities=[MessagingPort],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[],
        non_retryable_status_codes=[],
    ),
)
