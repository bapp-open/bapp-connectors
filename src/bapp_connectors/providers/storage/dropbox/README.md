# Dropbox

Dropbox file storage integration for upload, download, delete, and listing files.

- **API version:** v2
- **Base URL:** `https://api.dropboxapi.com/2/`
- **Content URL:** `https://content.dropboxapi.com/2` (uploads/downloads)
- **Auth:** OAuth2 Bearer token
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | Access Token | No | Yes |
| `app_key` | App Key | No | No |
| `app_secret` | App Secret | No | Yes |
| `refresh_token` | Refresh Token | No | Yes |
| `default_folder` | Default Folder | No | No |

When using OAuth, only `app_key` and `app_secret` are needed upfront. The
`token` and `refresh_token` are populated automatically after the OAuth flow.
For manual (non-OAuth) usage, provide a long-lived `token` directly.

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| `save` | Yes | Uploads via content endpoint; `autorename: true` by default |
| `open` | Yes | Downloads via content endpoint, returns BytesIO |
| `delete` | Yes | Silently ignores missing files (Django Storage convention) |
| `exists` | Yes | Uses `files/get_metadata` (no native exists endpoint) |
| `listdir` | Yes | Handles cursor-based pagination automatically |
| `size` | Yes | Uses `files/get_metadata` to read `size` field |
| `list_files` | Yes | Returns `FileInfo` with `path_display`, `server_modified` |
| `url` | No | Not implemented |
| `get_modified_time` | No | Not implemented (available via `list_files` metadata) |
| OAuthCapability | Yes | Full OAuth2 authorization code flow with refresh tokens |

## OAuth

| Parameter | Value |
|-----------|-------|
| Authorize URL | `https://www.dropbox.com/oauth2/authorize` |
| Token URL | `https://api.dropboxapi.com/oauth2/token` |
| Token access type | `offline` (returns refresh token) |
| Scopes | None (full access) |

The OAuth flow stores `token`, `app_key`, `app_secret`, and `refresh_token`
back into the connection credentials via `OAuthTokens.extra["credentials"]`.

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `users/get_current_account` | Test authentication |
| POST | `content.dropboxapi.com/2/files/upload` | Upload file |
| POST | `content.dropboxapi.com/2/files/download` | Download file |
| POST | `files/delete_v2` | Delete file or folder |
| POST | `files/list_folder` | List folder contents |
| POST | `files/list_folder/continue` | Continue paginated listing |
| POST | `files/get_metadata` | Check existence / get size |

## API Quirks

- **Two base URLs:** Metadata calls go to `api.dropboxapi.com/2/`, while file
  upload/download calls go to `content.dropboxapi.com/2`. The client handles
  this by passing absolute URLs for content operations.
- **Root path encoding:** Dropbox uses an empty string `""` for the root
  folder, not `"/"`. The client normalizes this automatically.
- **Upload metadata via header:** File uploads pass metadata (path, mode) in
  the `Dropbox-API-Arg` JSON header, not in the request body.
- **Download content via header:** File downloads send the path in
  `Dropbox-API-Arg` and return raw bytes in the response body.
- **Pagination:** `list_folder` returns a `has_more` flag and a `cursor` for
  continuation. The client follows all pages automatically.
- **No native exists:** There is no `exists` endpoint. The adapter calls
  `files/get_metadata` and catches exceptions.
- **Error 409 for path errors:** Dropbox returns HTTP 409 (conflict) for
  path-related errors like "not found", not 404.
