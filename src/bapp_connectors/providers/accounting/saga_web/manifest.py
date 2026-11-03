"""SAGA Web provider manifest."""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import AccountingPort
from bapp_connectors.core.types import AuthStrategy, ProviderFamily

# The key only travels over https to this host or a subdomain of it (adapter.base_url_error).
ALLOWED_HOST = "sagasoft.ro"
DEFAULT_BASE_URL = "https://web.sagasoft.ro/api/v20260225/"

manifest = ProviderManifest(
    name="saga_web",
    family=ProviderFamily.ACCOUNTING,
    display_name="SAGA Web",
    description=(
        "SAGA Web: trimite facturile, încasările, plățile și nomenclatoarele în contabilitate "
        "și citește situații (stocuri, solduri, balanță)."
    ),
    base_url=DEFAULT_BASE_URL,
    auth=AuthConfig(
        # the adapter sends its own headers (Bearer key + X-Saga-Cod-Fiscal)
        strategy=AuthStrategy.CUSTOM,
        # SAGA hands out a new key in X-Saga-Refresh-Token; the host must save it
        rotating_credentials=True,
        required_fields=[
            CredentialField(
                name="base_url",
                label="URL API",
                role="endpoint",
                default=DEFAULT_BASE_URL,
                help_text="URL-ul primit de la SAGA pentru firma ta, ex. https://web2.sagasoft.ro/sagac/api/v20260225/",
                colspan=24,
            ),
            CredentialField(name="cod_fiscal", label="Cod fiscal", help_text="Cifrele CUI-ului, fără RO.", colspan=8),
            CredentialField(
                name="token",
                label="Cheie de acces",
                sensitive=True,
                help_text="Generată în SAGA Web → Utilizatori → Integrare API. Se reînnoiește singură.",
                colspan=16,
            ),
        ],
    ),
    capabilities=[AccountingPort],
    rate_limit=RateLimitConfig(requests_per_second=2, burst=4),
    retry=RetryConfig(
        max_retries=2,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 207, 422],
    ),
)
