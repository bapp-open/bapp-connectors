"""
SFTP storage provider manifest — declares capabilities, auth, rate limits.

SFTP (SSH File Transfer Protocol) provides encrypted file access over SSH.
Available on virtually every Linux/Mac server via OpenSSH.
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
    name="sftp",
    family=ProviderFamily.STORAGE,
    display_name="SFTP",
    description="SFTP (SSH File Transfer Protocol) storage for secure file access to remote servers.",
    base_url="sftp://localhost/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="host", label="Hostname / IP", sensitive=False),
            CredentialField(name="username", label="Username", sensitive=False),
            CredentialField(
                name="password",
                label="Password",
                sensitive=True,
                required=False,
                help_text="Password for authentication. Leave empty if using SSH key.",
            ),
            CredentialField(
                name="private_key",
                label="SSH Private Key",
                sensitive=True,
                required=False,
                help_text="PEM-encoded private key. Either password or private_key is required.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="port",
                label="Port",
                field_type=FieldType.INT,
                default=22,
                help_text="SSH port (default: 22).",
            ),
            SettingsField(
                name="default_folder",
                label="Default Folder",
                field_type=FieldType.STR,
                default="/",
                help_text="Default remote directory for file operations.",
            ),
            SettingsField(
                name="verify_host_key",
                label="Verify Host Key",
                field_type=FieldType.BOOL,
                default=False,
                help_text="Reject connections to unknown hosts. Disable for first-time setup.",
            ),
            SettingsField(
                name="timeout",
                label="Timeout (seconds)",
                field_type=FieldType.INT,
                default=10,
                help_text="Connection timeout in seconds.",
            ),
        ],
    ),
    capabilities=[
        StoragePort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=20,
        burst=30,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[],
        non_retryable_status_codes=[],
    ),
)
