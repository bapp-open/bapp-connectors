# SFTP

SFTP (SSH File Transfer Protocol) storage for secure file access to remote servers.

- **Protocol:** SFTP over SSH (RFC 4253 / RFC 4254)
- **Default port:** 22
- **Auth:** Username + password or SSH private key (custom strategy, uses paramiko)
- **Rate limit:** 20 req/s, burst 30

## Conditional Registration

This provider **only registers if `paramiko` is installed**. If paramiko is
missing, the provider silently skips registration and is unavailable at runtime.

```bash
pip install paramiko
# or
pip install bapp-connectors[sftp]
```

## Credentials

| Field | Label | Required | Sensitive | Notes |
|-------|-------|----------|-----------|-------|
| `host` | Hostname / IP | Yes | No | |
| `username` | Username | Yes | No | |
| `password` | Password | No | Yes | Leave empty if using SSH key |
| `private_key` | SSH Private Key | No | Yes | PEM-encoded; RSA, Ed25519, or ECDSA |

Either `password` or `private_key` must be provided. The adapter's
`validate_credentials()` enforces this.

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `port` | Port | int | `22` | SSH port |
| `default_folder` | Default Folder | str | `/` | Default remote directory for file operations |
| `verify_host_key` | Verify Host Key | bool | `False` | Reject connections to unknown hosts |
| `timeout` | Timeout (seconds) | int | `10` | Connection timeout |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| `save` | Yes | Auto-creates intermediate directories |
| `open` | Yes | Downloads via `getfo`, returns BytesIO |
| `delete` | Yes | Silently ignores missing files (Django Storage convention) |
| `exists` | Yes | Uses `sftp.stat()` to check existence |
| `listdir` | Yes | Uses `listdir_attr()` for metadata-rich listing |
| `size` | Yes | Reads `st_size` from `sftp.stat()` |
| `list_files` | Yes | Returns `FileInfo` with size, modified_at, is_directory |
| `url` | No | Not implemented |
| `get_modified_time` | Yes | Returns `datetime` from `st_mtime` (UTC) |

## Connection Management

Each public method on `SFTPClient` opens a **fresh SSH transport and SFTP
session**, then closes both in a `finally` block. This avoids stale-connection
issues.

For batch operations, use the `connect()` context manager:

```python
with client.connect() as session:
    session.upload(data, "file.txt", "/uploads")
    session.download("/uploads/file.txt")
```

The `_SFTPSession` wrapper provides the same `upload`, `download`, `delete`,
and `exists` methods over a shared connection.

## SSH Key Support

The client supports three key types, tried in order:

1. RSA (`paramiko.RSAKey`)
2. Ed25519 (`paramiko.Ed25519Key`)
3. ECDSA (`paramiko.ECDSAKey`)

Pass the PEM-encoded private key string in the `private_key` credential field.

## API Quirks

- **No HTTP client:** This adapter uses `paramiko` directly, not
  `ResilientHttpClient`. The `http_client` parameter is accepted for interface
  compatibility but ignored.
- **Default folder handling:** Relative paths are prefixed with
  `default_folder` via `_with_base()`. Absolute paths bypass the default
  folder.
- **Recursive mkdir:** `_ensure_directory()` creates all intermediate
  directories by walking the path segments and calling `sftp.mkdir()` for
  each missing one.
- **Host key verification:** Disabled by default (`verify_host_key=False`).
  Enable in production for security. When disabled, paramiko accepts any
  host key.
- **Credential validation:** Unlike most providers that delegate to
  `manifest.auth.validate_credentials()`, the SFTP adapter has custom
  validation that ensures at least one of `password` or `private_key` is set.

## Integration Tests

Docker service for local testing:

| Service | Port | Username | Password |
|---------|------|----------|----------|
| SFTP | 2222 | testuser | testpass |
