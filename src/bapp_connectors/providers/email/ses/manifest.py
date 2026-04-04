"""
Amazon SES email provider manifest — declares capabilities, auth, and configuration.
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
from bapp_connectors.core.ports import EmailPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="ses",
    family=ProviderFamily.EMAIL,
    display_name="Amazon SES",
    description="Amazon Simple Email Service (SES) v2 integration.",
    base_url="https://email.amazonaws.com/",  # placeholder, boto3 handles URLs
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="access_key_id", label="Access Key ID", sensitive=False),
            CredentialField(name="secret_access_key", label="Secret Access Key", sensitive=True),
            CredentialField(name="from_email", label="Default From Email", sensitive=False),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="region",
                label="AWS Region",
                field_type=FieldType.STR,
                default="us-east-1",
                help_text="AWS region for SES.",
            ),
            SettingsField(
                name="configuration_set",
                label="Configuration Set",
                field_type=FieldType.STR,
                required=False,
                help_text="SES Configuration Set name for tracking.",
            ),
        ],
    ),
    capabilities=[EmailPort],
    rate_limit=RateLimitConfig(
        requests_per_second=1,
        burst=5,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[],
        non_retryable_status_codes=[],
    ),
)
