"""Manifestul Apple App Store."""

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
    WebhookConfig,
)
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="apple",
    family=ProviderFamily.APPSTORE,
    display_name="Apple App Store",
    description="App Store Connect: rapoarte de vanzari si financiare (luni fiscale), recenzii cu raspuns, "
    "abonamente si notificari App Store Server (cu cheia In-App Purchase).",
    base_url="https://api.appstoreconnect.apple.com/v1/",
    allow_multiple=True,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="issuer_id",
                label="Issuer ID",
                help_text="App Store Connect > Users and Access > Integrations > App Store Connect API.",
            ),
            CredentialField(
                name="key_id",
                label="Key ID",
                help_text="ID-ul cheii API; cheia trebuie sa aiba rolul Finance (sau Admin).",
            ),
            CredentialField(
                name="private_key",
                label="Cheia privata (.p8)",
                sensitive=True,
                help_text="Continutul fisierului AuthKey_XXXX.p8, inclusiv liniile BEGIN/END.",
            ),
            CredentialField(
                name="vendor_number",
                label="Vendor Number",
                help_text="App Store Connect > Payments and Financial Reports (numar de 8 cifre).",
            ),
            CredentialField(
                name="bundle_id",
                label="Bundle ID",
                required=False,
                help_text="Necesar doar pentru abonamente si notificari (App Store Server API).",
            ),
            CredentialField(
                name="iap_key_id",
                label="In-App Purchase Key ID",
                required=False,
                help_text="Users and Access > Integrations > In-App Purchase. Alta cheie decat cea App Store Connect.",
            ),
            CredentialField(
                name="iap_private_key", label="In-App Purchase cheia privata (.p8)", sensitive=True, required=False
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="include_free_apps",
                label="Include aplicatiile gratuite",
                field_type=FieldType.BOOL,
                default=True,
                help_text="Randurile cu 0 incasari (descarcari gratuite) intra in raportul de vanzari.",
            ),
            SettingsField(
                name="server_api_environment",
                label="Mediu App Store Server API",
                field_type=FieldType.SELECT,
                choices=["production", "sandbox"],
                default="production",
            ),
        ]
    ),
    capabilities=[AppStorePort, FinancialCapability, WebhookCapability],
    rate_limit=RateLimitConfig(requests_per_second=1.0, burst=5),
    retry=RetryConfig(
        max_retries=3, backoff=BackoffStrategy.EXPONENTIAL, non_retryable_status_codes=[400, 401, 403, 404]
    ),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="apple-jws",
        signature_header="",
        events=[
            "SUBSCRIBED",
            "DID_RENEW",
            "DID_FAIL_TO_RENEW",
            "EXPIRED",
            "DID_CHANGE_RENEWAL_STATUS",
            "REFUND",
            "REVOKE",
        ],
    ),
)
