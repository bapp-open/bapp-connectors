# WebDAV

WebDAV file storage integration for Nextcloud, ownCloud, cPanel, Apache mod_dav, and any WebDAV-compatible server.

- **Protocol:** WebDAV (RFC 4918) over HTTP/HTTPS
- **Base URL:** User-provided (e.g., `https://cloud.example.com/remote.php/dav/files/user`)
- **Auth:** HTTP Basic authentication
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `username` | Username | Yes | No |
| `password` | Password | Yes | Yes |
| `base_url` | WebDAV URL | Yes | No |

The `base_url` should be the full WebDAV endpoint URL including the path
prefix (e.g., `https://cloud.example.com/remote.php/dav/files/user`).

## Settings

| Field | Label | Type | Default | Description |
|-------|-------|------|---------|-------------|
| `default_folder` | Default Folder | str | `/` | Default remote folder for file operations |
| `verify_ssl` | Verify SSL | bool | `True` | Verify SSL certificates when connecting |
| `timeout` | Timeout (seconds) | int | `10` | HTTP request timeout |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| `save` | Yes | PUT with auto-created intermediate directories via MKCOL |
| `open` | Yes | GET, returns BytesIO |
| `delete` | Yes | DELETE; silently ignores missing files (Django Storage convention) |
| `exists` | Yes | PROPFIND depth 0; returns `True` on 200/207 |
| `listdir` | Yes | PROPFIND depth 1 with XML parsing |
| `size` | Yes | PROPFIND depth 0, reads `getcontentlength` from XML |
| `list_files` | Yes | Returns `FileInfo` with content_type, modified_at, size |
| `url` | No | Not implemented |
| `get_modified_time` | No | Not implemented (available via `list_files` metadata) |

## WebDAV Methods Used

| HTTP/WebDAV Method | Purpose |
|--------------------|---------|
| `OPTIONS` | Test connection (checks for `DAV` response header) |
| `PROPFIND` (depth 0) | Check existence, get file size, connection test fallback |
| `PROPFIND` (depth 1) | List directory contents with metadata |
| `PUT` | Upload / overwrite a file |
| `GET` | Download a file |
| `DELETE` | Delete a file or directory |
| `MKCOL` | Create a directory |

## PROPFIND XML Parsing

Directory listings use `PROPFIND` with depth 1 and parse the 207 Multi-Status
XML response. The following DAV properties are extracted:

| DAV Property | Maps to |
|-------------|---------|
| `resourcetype/collection` | `is_directory` |
| `displayname` | (not used; `name` is derived from href) |
| `getcontentlength` | `size` |
| `getlastmodified` | `modified_at` |
| `getcontenttype` | `content_type` |

The directory entry itself (matching the request URL) is always excluded from
the results.

## API Quirks

- **URL-based base:** Unlike other storage providers with fixed base URLs,
  WebDAV uses the user-provided `base_url` credential as the base for all
  requests. The adapter sets this on the `ResilientHttpClient`.
- **Path encoding:** URL segments are individually percent-encoded to handle
  filenames with special characters (spaces, unicode, etc.).
- **Directory trailing slash:** WebDAV servers expect directories to have a
  trailing `/` in URLs. The client appends slashes for PROPFIND and MKCOL
  requests.
- **MKCOL 405:** Some WebDAV servers return HTTP 405 (Method Not Allowed) when
  `MKCOL` is called on an existing directory. The `_ensure_directory()` method
  treats 405 as success.
- **Connection test:** The adapter tries `OPTIONS` first (looking for the
  `DAV` response header), then falls back to `PROPFIND` depth 0 if OPTIONS
  does not confirm WebDAV support.
- **Size via PROPFIND:** There is no simple HEAD-based size check. The adapter
  issues a `PROPFIND` depth 0 with a minimal XML body requesting only
  `getcontentlength`, then parses the XML response.
- **No content-type on upload:** The client does not set a `Content-Type`
  header on PUT uploads. The server typically infers it from the file
  extension.

## Integration Tests

Docker service for local testing:

| Service | Port | Username | Password |
|---------|------|----------|----------|
| WebDAV | 8080 | testuser | testpass |
