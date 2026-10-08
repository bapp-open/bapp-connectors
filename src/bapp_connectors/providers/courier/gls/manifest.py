"""
GLS courier provider manifest — declares capabilities, auth, rate limits.
"""

from bapp_connectors.core.capabilities import BatchTrackingCapability
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

PRINTER_TYPES = [
    "A4_2x2",
    "A4_4x1",
    "Connect",
    "Thermo",
    "ThermoZPL",
    "ThermoZPL_300DPI",
    "ShipItThermoPdf",
    "ShipItThermoZpl",
]

manifest = ProviderManifest(
    name="gls",
    family=ProviderFamily.COURIER,
    display_name="GLS",
    description="GLS courier integration for AWB generation, tracking, and shipment management.",
    # the real host depends on the `country` / `test` credentials; the client builds absolute URLs
    base_url="https://api.mygls.ro/ParcelService.svc/json/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="username", label="API Username (MyGLS e-mail)", sensitive=False),
            CredentialField(name="password", label="API Password", sensitive=True),
            CredentialField(name="client_number", label="Client Number", sensitive=False),
            CredentialField(
                name="country",
                label="Country",
                sensitive=False,
                default="RO",
                choices=["RO", "HU", "HR", "CZ", "SI", "SK", "RS"],
            ),
            CredentialField(
                name="test",
                label="Test environment",
                required=False,
                default="false",
                help_text="Use api.test.mygls.<country> (needs a test account from GLS; production logins do not work there).",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="printer_type",
                label="AWB Printer Format",
                field_type=FieldType.SELECT,
                default="Connect",
                choices=PRINTER_TYPES,
                help_text="Label format. ThermoZPL* / ShipItThermoZpl return ZPL, not PDF.",
            ),
            SettingsField(
                name="hide_phone_on_label",
                label="Hide phone numbers on the label",
                field_type=FieldType.BOOL,
                default=False,
            ),
            SettingsField(
                name="service_sm1",
                label="SMS service (SM1)",
                field_type=FieldType.BOOL,
                default=False,
                help_text="SMS to the recipient when the parcel is handed over to GLS.",
            ),
            SettingsField(
                name="service_sm1_text",
                label="SMS text (SM1)",
                field_type=FieldType.TEXTAREA,
                default="",
                help_text="Variables: #ParcelNr#, #COD#, #PickupDate#, #From_Name#, #ClientRef#.",
            ),
            SettingsField(
                name="service_sm2",
                label="SMS pre-advice (SM2)",
                field_type=FieldType.BOOL,
                default=False,
                help_text="SMS to the recipient on the delivery day.",
            ),
            SettingsField(
                name="service_fds",
                label="FlexDelivery (FDS)",
                field_type=FieldType.BOOL,
                default=False,
                help_text="E-mail with the estimated delivery window and delivery options.",
            ),
            SettingsField(
                name="service_fss",
                label="FlexDelivery SMS (FSS)",
                field_type=FieldType.BOOL,
                default=False,
                help_text="FlexDelivery by SMS; only together with FlexDelivery (FDS).",
            ),
        ],
    ),
    capabilities=[
        CourierPort,
        BatchTrackingCapability,
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
