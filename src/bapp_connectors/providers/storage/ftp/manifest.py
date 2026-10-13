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

SERVER = "FTP server"
OPTIONS = "Options"

manifest = ProviderManifest(
    name="ftp",
    family=ProviderFamily.STORAGE,
    display_name="FTP File Storage",
    description="FTP/FTPS file storage integration for upload, download, delete, and listing files.",
    base_url="ftp://localhost",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="host", label="FTP Host", sensitive=False, group=SERVER, colspan=16),
            CredentialField(name="port", label="FTP Port", sensitive=False, default="21", group=SERVER, colspan=8),
            CredentialField(name="username", label="Username", sensitive=False, group=SERVER, colspan=12),
            CredentialField(name="password", label="Password", sensitive=True, group=SERVER, colspan=12),
            CredentialField(
                name="use_tls",
                label="Use TLS",
                sensitive=False,
                required=False,
                default="false",
                choices=["true", "false"],
                group=SERVER,
            ),
            CredentialField(
                name="default_folder",
                label="Default Folder",
                sensitive=False,
                required=False,
                default="",
                help_text="Default base folder for file operations.",
                group=OPTIONS,
                colspan=16,
            ),
            CredentialField(
                name="timeout",
                label="Timeout (seconds)",
                sensitive=False,
                required=False,
                default="10",
                group=OPTIONS,
                colspan=8,
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
