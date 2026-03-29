# OneDrive

Microsoft OneDrive file storage integration via Microsoft Graph API.

- **API version:** Microsoft Graph v1.0
- **Base URL:** `https://graph.microsoft.com/v1.0/me/drive/`
- **Auth:** OAuth2 Bearer token (custom strategy)
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | Access Token | No | Yes |
| `refresh_token` | Refresh Token | No | Yes |
| `client_id` | Application (Client) ID | No | No |
| `client_secret` | Client Secret | No | Yes |

All credential fields are optional individually because the OAuth flow
populates them automatically. For manual usage, provide `token` directly.

## Settings

| Field | Label | Default | Description |
|-------|-------|---------|-------------|
| `default_folder` | Default Folder | `/` | Default folder path for file operations |

## Capabilities

| Capability | Supported | Notes |
|------------|-----------|-------|
| `save` | Yes | PUT to path creates or overwrites the file |
| `open` | Yes | Downloads via `{item}/content`, returns BytesIO |
| `delete` | Yes | Resolves metadata to get item ID, then deletes; silently ignores missing files |
| `exists` | Yes | Calls `get_item_metadata`; returns `True` if an `id` is present |
| `listdir` | Yes | Lists children via `{item}/children` endpoint |
| `size` | Yes | Reads `size` from item metadata |
| `list_files` | Yes | Returns `FileInfo` with mimeType, lastModifiedDateTime |
| `url` | No | Not implemented |
| `get_modified_time` | No | Not implemented (available via `list_files` metadata) |
| OAuthCapability | Yes | Full OAuth2 authorization code flow with refresh tokens |

## OAuth

| Parameter | Value |
|-----------|-------|
| Authorize URL | `https://login.microsoftonline.com/common/oauth2/v2.0/authorize` |
| Token URL | `https://login.microsoftonline.com/common/oauth2/v2.0/token` |
| Scopes | `Files.ReadWrite`, `offline_access` |
| Tenant | `common` (supports personal and organizational accounts) |

The OAuth flow stores `token`, `refresh_token`, `client_id`, and
`client_secret` back into the connection credentials via
`OAuthTokens.extra["credentials"]`. Microsoft may issue a new refresh token on
each refresh -- the adapter stores whichever token the response contains.

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `root` | Test authentication |
| GET | `{item}/children` | List folder contents |
| GET | `{item}` | Get item metadata |
| GET | `{item}/content` | Download file content |
| PUT | `{item}/content` | Upload / overwrite file (up to 4 MB) |
| POST | `{parent}/children` | Create folder |
| DELETE | `items/{id}` | Delete item |

## Path Encoding

OneDrive supports **path-based access** via the Graph API. The client builds
item references using the pattern:

- `/foo/bar.txt` becomes `root:/foo/bar.txt:`
- `/` or empty becomes `root`

This is handled by `_item_path()` in the client.

## API Quirks

- **Path-based access:** Unlike Google Drive, OneDrive supports path-based
  references directly (`root:/path/to/file:`), so no ID resolution loop is
  needed.
- **Upload size limit:** The simple PUT upload supports files up to **4 MB**.
  Larger files require an upload session (not yet implemented).
- **Folder creation conflict:** Folder creation uses
  `@microsoft.graph.conflictBehavior: "rename"` to avoid errors if the folder
  already exists.
- **Delete requires item ID:** Deletion resolves the path to metadata first to
  extract the item `id`, then deletes via `items/{id}`.
- **Rotating refresh tokens:** Microsoft may return a new `refresh_token` on
  each token refresh. The adapter always stores the latest refresh token from
  the response, falling back to the previous one if absent.
- **Common tenant:** The OAuth URLs use `/common/` which supports both personal
  Microsoft accounts and organizational (Azure AD) accounts.
