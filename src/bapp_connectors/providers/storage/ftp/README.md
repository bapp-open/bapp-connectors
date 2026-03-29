# FTP File Storage

FTP/FTPS file storage integration for upload, download, delete, and listing files.

- **Protocol:** FTP (RFC 959) / FTPS (RFC 4217)
- **Default port:** 21
- **Auth:** Username + password (custom strategy, uses ftplib directly)
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive | Default |
|-------|-------|----------|-----------|---------|
| `host` | FTP Host | Yes | No | |
| `port` | FTP Port | Yes | No | `21` |
| `username` | Username | Yes | No | |
| `password` | Password | Yes | Yes | |
| `use_tls` | Use TLS | No | No | `false` |
| `default_folder` | Default Folder | No | No | `""` |
| `timeout` | Timeout (seconds) | No | No | `10` |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| `save` | Yes | Auto-creates intermediate directories via `_ensure_directory` |
| `open` | Yes | Downloads via `RETR`, returns BytesIO |
| `delete` | Yes | Silently ignores missing files (Django Storage convention) |
| `exists` | Yes | Tries `SIZE` for files, `CWD` for directories |
| `listdir` | Yes | Uses `NLST`; detects directories via `CWD` probe |
| `size` | Yes | Uses FTP `SIZE` command |
| `list_files` | Yes | Returns `FileInfo` with name, size, is_directory |
| `url` | No | Not implemented |
| `get_modified_time` | No | Not implemented |

## Settings

| Field | Label | Default | Description |
|-------|-------|---------|-------------|
| `use_tls` | Use TLS | `false` | Upgrades to FTPS (`FTP_TLS`) with `prot_p()` |
| `default_folder` | Default Folder | `""` | Base folder prepended to relative paths |
| `timeout` | Timeout | `10` | Connection timeout in seconds |

## Connection Management

The FTP client creates a **new connection for each operation**. This avoids
stale-connection issues common with FTP. Each method:

1. Calls `_connect()` to establish a fresh FTP/FTPS connection
2. Performs the operation
3. Calls `connection.quit()` in a `finally` block

## API Quirks

- **No HTTP client:** This adapter uses Python's `ftplib` directly, not
  `ResilientHttpClient`. The `http_client` parameter is accepted for interface
  compatibility but ignored.
- **Default folder handling:** Relative paths are prefixed with `default_folder`
  via `_with_base()`. Absolute paths (starting with `/`) bypass the default
  folder entirely.
- **Directory detection:** FTP has no standard way to distinguish files from
  directories in `NLST` output. The client probes each entry with `CWD` to
  determine if it is a directory, which can be slow for large listings.
- **FTPS data protection:** When `use_tls=true`, the client calls `prot_p()`
  after login to enable encrypted data transfers.
- **Auto-create directories:** `save()` and `upload_file()` call
  `_ensure_directory()` which recursively creates missing directories using
  `MKD`.
- **Host fallback:** If `host` is empty but `username` contains `@`, the host
  is extracted from the username (e.g., `user@ftp.example.com`).

## Integration Tests

Docker service for local testing:

| Service | Port | Username | Password |
|---------|------|----------|----------|
| FTP | 2121 | testuser | testpass |
