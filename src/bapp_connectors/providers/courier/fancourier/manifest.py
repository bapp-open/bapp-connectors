"""
FAN Courier provider manifest — REST API v2 (https://api.fancourier.ro).

Source: the official "API Documentation FAN Courier V2.0" PDF (September 2025,
changelog to 13.08.2025). FAN publishes a test account on the production API:
username `clienttest`, password `testing`, clientId 7032158.
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
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

FAN_API_URL = "https://api.fancourier.ro/"

manifest = ProviderManifest(
    name="fancourier",
    family=ProviderFamily.COURIER,
    display_name="FAN Courier",
    description="FAN Courier — AWB generation, labels, tracking and cancellation (API v2).",
    base_url=FAN_API_URL,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="username", label="selfAWB username"),
            CredentialField(name="password", label="selfAWB password", sensitive=True),
            CredentialField(
                name="client_id",
                label="Client ID (branch)",
                required=False,
                help_text="The selfAWB branch id. Empty: the first branch of the account.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="service",
                label="Default service",
                field_type=FieldType.STR,
                default="Standard",
                help_text="FAN service name (Standard, RedCode, Express Loco 2H, FANbox...).",
            ),
            SettingsField(
                name="cod_to_bank_account",
                label="Cash on delivery to bank account (Cont Colector)",
                field_type=FieldType.BOOL,
                default=True,
                help_text="With cash on delivery, switch to the service's Cont Colector variant, so FAN "
                "transfers the money to your account instead of returning it on a separate AWB.",
            ),
            SettingsField(
                name="payer",
                label="Shipping paid by",
                field_type=FieldType.SELECT,
                choices=["sender", "recipient"],
                default="sender",
            ),
            SettingsField(
                name="label_format",
                label="Label format",
                field_type=FieldType.SELECT,
                choices=["A4", "A5", "A6"],
                default="A4",
                help_text="A6 is only available with ePOD.",
            ),
        ],
    ),
    capabilities=[CourierPort],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 422],
    ),
)
