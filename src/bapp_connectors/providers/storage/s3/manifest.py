"""
S3-compatible storage provider manifest.

Works with AWS S3, MinIO, DigitalOcean Spaces, Backblaze B2,
Cloudflare R2, and any S3-compatible API.
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
    name="s3",
    family=ProviderFamily.STORAGE,
    display_name="S3 Storage",
    description="S3-compatible object storage (AWS S3, MinIO, DigitalOcean Spaces, Backblaze B2, Cloudflare R2).",
    base_url="https://s3.amazonaws.com/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="access_key_id", label="Access Key ID", sensitive=False),
            CredentialField(name="secret_access_key", label="Secret Access Key", sensitive=True),
            CredentialField(name="bucket", label="Bucket Name", sensitive=False),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="endpoint_url",
                label="Endpoint URL",
                field_type=FieldType.STR,
                required=False,
                help_text="Custom S3 endpoint for non-AWS services (e.g. http://minio:9000, https://nyc3.digitaloceanspaces.com). Leave empty for AWS S3.",
            ),
            SettingsField(
                name="region",
                label="Region",
                field_type=FieldType.STR,
                default="us-east-1",
                help_text="AWS region or compatible region identifier.",
            ),
            SettingsField(
                name="default_prefix",
                label="Default Prefix",
                field_type=FieldType.STR,
                default="",
                help_text="Default key prefix for all operations (e.g. 'uploads/' or 'tenant-123/').",
            ),
            SettingsField(
                name="addressing_style",
                label="Addressing Style",
                field_type=FieldType.SELECT,
                choices=["auto", "path", "virtual"],
                default="auto",
                help_text="S3 addressing style. Use 'path' for MinIO/local S3. 'auto' works for AWS.",
            ),
        ],
    ),
    capabilities=[
        StoragePort,
    ],
    rate_limit=RateLimitConfig(
        requests_per_second=100,
        burst=200,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
