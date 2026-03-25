"""
Dropbox provider manifest — declares capabilities, auth, rate limits.
"""

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import StoragePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="dropbox",
    family=ProviderFamily.STORAGE,
    display_name="Dropbox",
    description="Dropbox file storage integration for upload, download, delete, and listing files.",
    base_url="https://api.dropboxapi.com/2/",
    auth=AuthConfig(
        strategy=AuthStrategy.BEARER,
        required_fields=[
            CredentialField(name="token", label="Access Token", sensitive=True, required=False),
            CredentialField(name="app_key", label="App Key", sensitive=False, required=False),
            CredentialField(name="app_secret", label="App Secret", sensitive=True, required=False),
            CredentialField(name="refresh_token", label="Refresh Token", sensitive=True, required=False),
            CredentialField(
                name="default_folder",
                label="Default Folder",
                sensitive=False,
                required=False,
                default="/",
                help_text="Default folder path for file operations.",
            ),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="app_key", label="App Key", sensitive=False),
                CredentialField(name="app_secret", label="App Secret", sensitive=True),
            ],
            scopes=[],
            display_name="Connect with Dropbox",
        ),
    ),
    capabilities=[StoragePort, OAuthCapability],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 409],
    ),
)
