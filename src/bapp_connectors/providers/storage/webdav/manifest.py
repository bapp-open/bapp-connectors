"""
WebDAV storage provider manifest — declares capabilities, auth, rate limits.

WebDAV is a standard HTTP extension for file management supported by Nextcloud,
ownCloud, cPanel, Apache mod_dav, etc.
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
from bapp_connectors.core.ports import StoragePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="webdav",
    family=ProviderFamily.STORAGE,
    display_name="WebDAV",
    description="WebDAV file storage integration (Nextcloud, ownCloud, cPanel, Apache mod_dav, etc.).",
    base_url="https://webdav.example.com/",
    auth=AuthConfig(
        strategy=AuthStrategy.BASIC,
        required_fields=[
            CredentialField(name="username", label="Username", sensitive=False),
            CredentialField(name="password", label="Password", sensitive=True),
            CredentialField(
                name="base_url",
                label="WebDAV URL",
                sensitive=False,
                help_text="Full WebDAV URL including path, e.g. https://cloud.example.com/remote.php/dav/files/user",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_folder",
                label="Default Folder",
                field_type=FieldType.STR,
                default="/",
                help_text="Default remote folder for file operations.",
            ),
            SettingsField(
                name="verify_ssl",
                label="Verify SSL",
                field_type=FieldType.BOOL,
                default=True,
                help_text="Verify SSL certificates when connecting.",
            ),
            SettingsField(
                name="timeout",
                label="Timeout (seconds)",
                field_type=FieldType.INT,
                default=10,
                help_text="HTTP request timeout in seconds.",
            ),
        ],
    ),
    capabilities=[
        StoragePort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404, 405],
    ),
)
