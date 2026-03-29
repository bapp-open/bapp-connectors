# Google Drive

Google Drive file storage integration for upload, download, delete, and listing files.

- **API version:** Drive API v3
- **Base URL:** `https://www.googleapis.com/drive/v3/`
- **Upload URL:** `https://www.googleapis.com/upload/drive/v3`
- **Auth:** OAuth2 Bearer token (custom strategy)
- **Rate limit:** 10 req/s, burst 20

## Credentials

| Field | Label | Required | Sensitive |
|-------|-------|----------|-----------|
| `token` | Access Token | No | Yes |
| `refresh_token` | Refresh Token | No | Yes |
| `client_id` | Client ID | No | No |
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
| `save` | Yes | Creates folders as needed; overwrites existing files |
| `open` | Yes | Resolves path to file ID, downloads via `alt=media` |
| `delete` | Yes | Silently ignores missing files (Django Storage convention) |
| `exists` | Yes | Resolves path to file ID; returns `True` if found |
| `listdir` | Yes | Lists children of resolved folder ID |
| `size` | Yes | Reads `size` from file metadata |
| `list_files` | Yes | Returns `FileInfo` with mimeType, modifiedTime, size |
| `url` | No | Not implemented |
| `get_modified_time` | No | Not implemented (available via `list_files` metadata) |
| OAuthCapability | Yes | Full OAuth2 authorization code flow with refresh tokens |

## OAuth

| Parameter | Value |
|-----------|-------|
| Authorize URL | `https://accounts.google.com/o/oauth2/v2/auth` |
| Token URL | `https://oauth2.googleapis.com/token` |
| Scopes | `https://www.googleapis.com/auth/drive.file` |
| Access type | `offline` |
| Prompt | `consent` (forces refresh token on each authorization) |

The OAuth flow stores `token`, `refresh_token`, `client_id`, and
`client_secret` back into the connection credentials via
`OAuthTokens.extra["credentials"]`.

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `about?fields=user` | Test authentication |
| GET | `files?q=...` | List files in a folder |
| GET | `files/{id}?fields=...` | Get file metadata |
| GET | `files/{id}?alt=media` | Download file content |
| POST | `upload/drive/v3/files?uploadType=multipart` | Upload new file |
| PATCH | `upload/drive/v3/files/{id}?uploadType=media` | Update existing file |
| POST | `files` (with folder mimeType) | Create folder |
| DELETE | `files/{id}` | Delete file |

## Path Resolution

Google Drive is **ID-based**, not path-based. The adapter translates
human-readable paths (e.g., `/invoices/2024/report.pdf`) to Google Drive file
IDs using the `find_by_path()` method, which:

1. Splits the path into segments
2. Queries each segment with `name='segment' in parents` starting from `root`
3. Caches resolved IDs in `_path_cache` to avoid redundant API calls

Folder creation (`ensure_folder_path()`) follows the same approach, creating
missing folders with `mimeType=application/vnd.google-apps.folder`.

## API Quirks

- **ID-based, not path-based:** Every file/folder operation requires resolving
  a path to an ID first. This adds 1 API call per path segment on the first
  access (cached afterward).
- **Multipart upload:** File uploads use `multipart/related` with a JSON
  metadata part and an octet-stream data part, separated by a custom boundary.
- **Save overwrites:** `save()` checks if a file already exists at the path.
  If found, it updates the content via `PATCH`; otherwise, it creates a new
  file via `POST`.
- **Folder detection:** Folders are identified by
  `mimeType=application/vnd.google-apps.folder`.
- **No trash on delete:** `delete()` permanently deletes (does not move to
  trash). The Drive API `DELETE` endpoint bypasses the trash.
- **File fields:** All file metadata requests specify
  `fields=id,name,mimeType,size,modifiedTime,parents` to minimize response
  size.
