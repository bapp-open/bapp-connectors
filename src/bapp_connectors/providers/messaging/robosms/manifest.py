"""
RoboSMS provider manifest — declares capabilities, auth, rate limits.
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
    name="robosms",
    family=ProviderFamily.MESSAGING,
    display_name="RoboSMS",
    description="RoboSMS integration for sending SMS messages.",
    base_url="https://robo-sms.com/api/",
    auth=AuthConfig(
        strategy=AuthStrategy.TOKEN,
        required_fields=[
            CredentialField(name="token", label="API Token", sensitive=True),
            CredentialField(
                name="device_id",
                label="Device ID",
                sensitive=False,
                required=False,
                help_text="The device used to send SMS.",
            ),
        ],
    ),
    capabilities=[MessagingPort],
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
