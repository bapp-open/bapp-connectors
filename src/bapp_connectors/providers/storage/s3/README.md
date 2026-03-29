# S3 Storage

S3-compatible object storage integration (AWS S3, MinIO, DigitalOcean Spaces, Backblaze B2, Cloudflare R2).

- **Protocol:** S3 API (AWS Signature Version 4)
- **Default base URL:** `https://s3.amazonaws.com/`
- **Auth:** Access Key ID + Secret Access Key (custom strategy, uses boto3)
- **Rate limit:** 100 req/s, burst 200

## Conditional Registration

This provider **only registers if `boto3` is installed**. If boto3 is missing,
the provider silently skips registration and is unavailable at runtime.

```bash
pip install boto3
# or
pip install bapp-connectors[s3]
```

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `access_key_id` | Access Key ID | Yes | No |
| `secret_access_key` | Secret Access Key | Yes | Yes |
| `bucket` | Bucket Name | Yes | No |

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `endpoint_url` | Endpoint URL | str | `""` | Custom S3 endpoint for non-AWS services (e.g., `http://minio:9000`). Leave empty for AWS S3. |
| `region` | Region | str | `us-east-1` | AWS region or compatible region identifier |
| `default_prefix` | Default Prefix | str | `""` | Key prefix prepended to all operations (e.g., `uploads/` or `tenant-123/`) |
| `addressing_style` | Addressing Style | select | `auto` | S3 addressing style: `auto`, `path`, or `virtual`. Use `path` for MinIO/local S3. |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| `save` | Yes | `PutObject` -- uploads bytes to a key |
| `open` | Yes | `GetObject` -- downloads and returns BytesIO |
| `delete` | Yes | `DeleteObject` -- idempotent (does not raise if key missing) |
| `exists` | Yes | `HeadObject` -- returns `True` if key exists |
| `listdir` | Yes | `ListObjectsV2` with delimiter `/` for directory-like listing |
| `size` | Yes | `HeadObject` -- reads `ContentLength` |
| `url` | Yes | Generates unsigned URL (endpoint-aware) |
| `list_files` | Yes | Returns `FileInfo` with size, last_modified, is_directory |
| `get_modified_time` | Yes | Returns `LastModified` from `HeadObject` |

## S3 Operations Mapping

| StoragePort Method | S3 API Call |
|--------------------|------------|
| `save()` | `PutObject` |
| `open()` | `GetObject` |
| `delete()` | `DeleteObject` |
| `exists()` | `HeadObject` |
| `listdir()` | `ListObjectsV2` (with delimiter) |
| `size()` | `HeadObject` |
| `url()` | URL construction (no presigning) |
| `test_connection()` | `HeadBucket` |

## URL Generation

`url()` generates an unsigned (public) URL:

- **AWS S3:** `https://{bucket}.s3.amazonaws.com/{key}`
- **Custom endpoint:** `{endpoint_url}/{bucket}/{key}`

For presigned URLs, use the boto3 client directly.

## API Quirks

- **No HTTP client:** This adapter uses `boto3` directly, not
  `ResilientHttpClient`. Boto3 handles SigV4 auth, retries, and connection
  pooling internally. The `http_client` parameter is accepted for interface
  compatibility but ignored.
- **Key prefixing:** The `default_prefix` setting is prepended to all keys
  via `_key()`. This allows tenant isolation or folder-like organization
  without changing application code.
- **Flat namespace:** S3 has no real directories. `listdir()` uses
  `ListObjectsV2` with `Delimiter="/"` to simulate directory listing.
  "Directories" are returned as `CommonPrefixes`.
- **Idempotent delete:** `DeleteObject` never raises an error, even if the
  key does not exist. This matches the Django Storage convention.
- **Addressing style:** Use `path` for MinIO and local S3-compatible services.
  Use `auto` (default) for AWS S3, which will use virtual-hosted style.
- **Retry handling:** boto3 is configured with `max_attempts=3` and `standard`
  retry mode. The framework-level retry config is not used.

## Integration Tests

Docker service for local testing (MinIO):

| Service | Port | Access Key | Secret Key | Bucket |
|---------|------|------------|------------|--------|
| MinIO | 19000 | minioadmin | minioadmin | test-bucket |
