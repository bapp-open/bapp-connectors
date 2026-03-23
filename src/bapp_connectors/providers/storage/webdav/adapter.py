"""
WebDAV storage adapter — implements StoragePort.

Supports any WebDAV-compatible server: Nextcloud, ownCloud, cPanel, Apache mod_dav, etc.
"""

from __future__ import annotations

import posixpath
from io import BytesIO
from typing import IO

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.http import BasicAuth, ResilientHttpClient
from bapp_connectors.core.ports import FileInfo, StoragePort
from bapp_connectors.providers.storage.webdav.client import WebDAVApiClient
from bapp_connectors.providers.storage.webdav.manifest import manifest


class WebDAVStorageAdapter(StoragePort):
    """
    WebDAV storage adapter.

    Implements:
    - StoragePort: save, open, delete, exists, listdir, size, list_files
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        username = credentials.get("username", "")
        password = credentials.get("password", "")
        base_url = credentials.get("base_url", "")
        if base_url and not base_url.endswith("/"):
            base_url += "/"

        default_folder = config.get("default_folder", "/")
        verify_ssl = config.get("verify_ssl", True)
        timeout = config.get("timeout", 10)

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(username=username, password=password),
                provider_name="webdav",
            )
        else:
            http_client.base_url = base_url

        self.client = WebDAVApiClient(
            http_client=http_client,
            default_folder=default_folder,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="WebDAV server reachable" if success else "Connection failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── StoragePort (Django Storage API) ──

    def save(self, name: str, content: bytes | IO) -> str:
        if isinstance(content, bytes):
            data = content
        else:
            data = content.read()
        directory = posixpath.dirname(name) or "/"
        file_name = posixpath.basename(name)
        self.client.upload(data, file_name, directory)
        return name

    def open(self, name: str) -> IO:
        data = self.client.download(name)
        return BytesIO(data)

    def delete(self, name: str) -> None:
        try:
            self.client.delete(name)
        except Exception:
            pass

    def exists(self, name: str) -> bool:
        try:
            url = self.client._build_url(name)
            resp = self.client.http.call(
                "PROPFIND", url, direct_response=True,
                headers={"Depth": "0"}, timeout=self.client._timeout,
            )
            return resp.status_code in (200, 207)
        except Exception:
            return False

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        entries = self.client.list_directory(path)
        dirs = [e["name"] for e in entries if e.get("is_directory")]
        files = [e["name"] for e in entries if not e.get("is_directory")]
        return dirs, files

    def size(self, name: str) -> int:
        try:
            url = self.client._build_url(name)
            resp = self.client.http.call(
                "PROPFIND", url, direct_response=True,
                headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
                data='<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop><D:getcontentlength/></D:prop></D:propfind>',
                timeout=self.client._timeout,
            )
            if resp.status_code in (200, 207):
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                cl = root.find(".//{DAV:}getcontentlength")
                if cl is not None and cl.text:
                    return int(cl.text)
        except Exception:
            pass
        return 0

    # ── Convenience override with richer metadata ──

    def list_files(self, remote_path: str = "/") -> list[FileInfo]:
        entries = self.client.list_directory(remote_path)
        return [
            FileInfo(
                path=entry["href"],
                name=entry["name"],
                size=entry["size"],
                content_type=entry["content_type"],
                modified_at=entry["modified_at"],
                is_directory=entry["is_directory"],
            )
            for entry in entries
        ]
