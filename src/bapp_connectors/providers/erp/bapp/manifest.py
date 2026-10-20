"""BAPP ERP provider manifest."""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import ErpPort, MessagingPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

# The token only travels over https to this host or a subdomain of it (adapter.base_url_error).
ALLOWED_HOST = "bapp.ro"

manifest = ProviderManifest(
    name="bapp",
    family=ProviderFamily.ERP,
    display_name="BAPP",
    description="BAPP ERP: print files and send SMS through the company's registered devices and phones.",
    base_url="https://panel.bapp.ro/api/",
    auth=AuthConfig(
        strategy=AuthStrategy.TOKEN,
        required_fields=[
            CredentialField(name="token", label="API token", sensitive=True, colspan=12),
            CredentialField(name="tenant_id", label="Company ID", colspan=12),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="base_url",
                label="API URL",
                default="https://panel.bapp.ro/api/",
                help_text="Change only for another BAPP environment; must be https on bapp.ro or a subdomain.",
                colspan=24,
            ),
        ],
    ),
    capabilities=[ErpPort, MessagingPort],
    rate_limit=RateLimitConfig(requests_per_second=5, burst=10),
    retry=RetryConfig(
        max_retries=0,
        backoff=BackoffStrategy.NONE,
        retryable_status_codes=[],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
