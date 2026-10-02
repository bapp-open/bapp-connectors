"""Manifestul Steam (Steamworks partner API)."""

from bapp_connectors.core.capabilities import FinancialCapability
from bapp_connectors.core.manifest import AuthConfig, CredentialField, ProviderManifest, RateLimitConfig, RetryConfig
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="steam",
    family=ProviderFamily.APPSTORE,
    display_name="Steam",
    description="Steamworks: vanzari detaliate pe zi (IPartnerFinancialsService), rambursari si recenzii publice. "
    "Cheia financiara are IP whitelist in Steamworks; adauga IP-ul de iesire al serverului.",
    base_url="https://partner.steam-api.com/",
    allow_multiple=True,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="financial_api_key", label="Financial Web API Key", sensitive=True, help_text="Steamworks > Users & Permissions > Manage Groups > Financial API Group > Web API Key."),
            CredentialField(name="app_ids", label="App IDs", help_text="Separate prin virgula (ex. 4000, 4001)."),
        ],
    ),
    capabilities=[AppStorePort, FinancialCapability],
    rate_limit=RateLimitConfig(requests_per_second=1.0, burst=3),
    retry=RetryConfig(max_retries=3, backoff=BackoffStrategy.EXPONENTIAL, non_retryable_status_codes=[400, 401, 403, 404]),
)
