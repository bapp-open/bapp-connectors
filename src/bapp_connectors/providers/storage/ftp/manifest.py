"""
FTP provider manifest — declares capabilities, auth, and configuration.
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
)
from bapp_connectors.core.ports import StoragePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="ftp",
    family=ProviderFamily.STORAGE,
    display_name="FTP File Storage",
    description="FTP/FTPS file storage integration for upload, download, delete, and listing files.",
    base_url="ftp://localhost",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="host", label="FTP Host", sensitive=False),
            CredentialField(name="port", label="FTP Port", sensitive=False, default="21"),
            CredentialField(name="username", label="Username", sensitive=False),
            CredentialField(name="password", label="Password", sensitive=True),
            CredentialField(
                name="use_tls",
                label="Use TLS",
                sensitive=False,
                required=False,
                default="false",
                choices=["true", "false"],
            ),
            CredentialField(
                name="default_folder",
                label="Default Folder",
                sensitive=False,
                required=False,
                default="",
                help_text="Default base folder for file operations.",
            ),
            CredentialField(
                name="timeout",
                label="Timeout (seconds)",
                sensitive=False,
                required=False,
                default="10",
            ),
        ],
    ),
    capabilities=[StoragePort],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[],
        non_retryable_status_codes=[],
    ),
)
