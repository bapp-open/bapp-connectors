"""
Google Drive provider manifest — declares capabilities, auth, rate limits.
"""

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    OAuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import StoragePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="google_drive",
    family=ProviderFamily.STORAGE,
    display_name="Google Drive",
    description="Google Drive file storage integration for upload, download, delete, and listing files.",
    base_url="https://www.googleapis.com/drive/v3/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="token", label="Access Token", sensitive=True, required=False),
            CredentialField(name="refresh_token", label="Refresh Token", sensitive=True, required=False),
            CredentialField(name="client_id", label="Client ID", sensitive=False, required=False),
            CredentialField(name="client_secret", label="Client Secret", sensitive=True, required=False),
        ],
        oauth=OAuthConfig(
            credential_fields=[
                CredentialField(name="client_id", label="Client ID", sensitive=False),
                CredentialField(name="client_secret", label="Client Secret", sensitive=True),
            ],
            scopes=["https://www.googleapis.com/auth/drive.file"],
            display_name="Connect with Google Drive",
        ),
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_folder",
                label="Default Folder",
                field_type=FieldType.STR,
                default="/",
                help_text="Default folder path for file operations.",
            ),
        ],
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
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
