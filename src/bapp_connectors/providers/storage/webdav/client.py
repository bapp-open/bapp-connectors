"""
WebDAV storage client — raw HTTP calls only, no business logic.

WebDAV extends HTTP with methods: PROPFIND, MKCOL, COPY, MOVE, LOCK, UNLOCK.
Auth is HTTP Basic. All paths are relative to the base_url.
"""

from __future__ import annotations

import logging
import os
import posixpath
import urllib.parse
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

_DAV_NS = "{DAV:}"

_PROPFIND_BODY = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:resourcetype/>
    <D:displayname/>
    <D:getcontentlength/>
    <D:getlastmodified/>
    <D:getcontenttype/>
  </D:prop>
</D:propfind>"""


class WebDAVApiClient:
    """
    Low-level WebDAV client.

    Handles raw HTTP/WebDAV calls: PUT (upload), GET (download), DELETE,
    PROPFIND (list/stat), MKCOL (mkdir), OPTIONS (capabilities check).
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        default_folder: str = "/",
        timeout: int = 10,
        verify_ssl: bool = True,
    ):
        self.http = http_client
        self._default_folder = default_folder.strip() or "/"
        self._timeout = timeout
        self._verify_ssl = verify_ssl

    # ── Path utilities ──

    def _with_base(self, path: str) -> str:
        """Prefix a relative path with the default folder."""
        if not path:
            path = ""
        if path.startswith("/"):
            return path
        base = ("/" + self._default_folder.strip("/")).rstrip("/")
        if not path or path.strip() == ".":
            return base or "/"
        return posixpath.join(base, path.lstrip("/"))

    def _normalize(self, path: str) -> str:
        """Normalize a path: leading /, no trailing / (except root)."""
        if not path:
            return ""
        joined = posixpath.normpath("/" + path.strip())
        if joined != "/":
            joined = joined.rstrip("/")
        return joined

    def _build_url(self, path: str) -> str:
        """Build a full URL from a normalized path, URL-encoding segments."""
        norm = self._normalize(self._with_base(path))
        segments = [urllib.parse.quote(seg, safe="") for seg in norm.split("/") if seg]
        suffix = "/".join(segments)
        return urllib.parse.urljoin(self.http.base_url, suffix)

    def _build_url_raw(self, path: str) -> str:
        """Build URL without prepending default_folder."""
        norm = self._normalize(path)
        segments = [urllib.parse.quote(seg, safe="") for seg in norm.split("/") if seg]
        suffix = "/".join(segments)
        return urllib.parse.urljoin(self.http.base_url, suffix)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials via OPTIONS + DAV header check, fallback to PROPFIND depth 0."""
        try:
            # Try OPTIONS first
            resp = self.http.call("OPTIONS", "", direct_response=True, timeout=self._timeout)
            if resp.ok and any(h.lower() == "dav" for h in resp.headers.keys()):
                return True
            # Fallback: PROPFIND depth 0
            resp = self.http.call(
                "PROPFIND", "", direct_response=True,
                headers={"Depth": "0"}, timeout=self._timeout,
            )
            return resp.status_code in (200, 207)
        except Exception:
            return False

    # ── Upload ──

    def upload(self, file_data: bytes, file_name: str, remote_path: str) -> None:
        """PUT a file to the server, creating intermediate directories as needed."""
        target_dir = self._normalize(self._with_base(remote_path))
        self._ensure_directory(target_dir)
        url = self._build_url(posixpath.join(remote_path, file_name))
        resp = self.http.call("PUT", url, direct_response=True, data=file_data, timeout=self._timeout)
        if resp.status_code not in (200, 201, 204):
            resp.raise_for_status()

    # ── Download ──

    def download(self, remote_path: str) -> bytes:
        """GET a file from the server."""
        url = self._build_url(remote_path)
        resp = self.http.call("GET", url, direct_response=True, timeout=self._timeout)
        if resp.status_code != 200:
            resp.raise_for_status()
        return resp.content

    # ── Delete ──

    def delete(self, remote_path: str) -> None:
        """DELETE a file or directory from the server."""
        url = self._build_url(remote_path)
        resp = self.http.call("DELETE", url, direct_response=True, timeout=self._timeout)
        if resp.status_code not in (200, 204):
            resp.raise_for_status()

    # ── List (PROPFIND) ──

    def list_directory(self, remote_path: str) -> list[dict]:
        """
        PROPFIND depth 1 on a directory. Returns list of dicts with keys:
        href, name, size, content_type, modified_at, is_directory.
        """
        url = self._build_url(remote_path)
        if not url.endswith("/"):
            url += "/"

        resp = self.http.call(
            "PROPFIND", url, direct_response=True,
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            data=_PROPFIND_BODY,
            timeout=self._timeout,
        )
        if resp.status_code not in (200, 207):
            resp.raise_for_status()

        return self._parse_propfind_response(resp.content, url)

    def _parse_propfind_response(self, xml_bytes: bytes, request_url: str) -> list[dict]:
        """Parse a PROPFIND 207 Multi-Status XML response into a list of file entries."""
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return []

        # Normalize the request URL path to skip the directory entry itself
        request_path = urllib.parse.urlparse(request_url).path
        if not request_path.endswith("/"):
            request_path += "/"

        results = []
        for response_el in root.iter(f"{_DAV_NS}response"):
            href_el = response_el.find(f"{_DAV_NS}href")
            if href_el is None or not href_el.text:
                continue

            href = urllib.parse.unquote(href_el.text)
            # Skip the directory itself
            href_normalized = href if href.endswith("/") else href + "/"
            req_normalized = request_path if request_path.endswith("/") else request_path + "/"
            if href_normalized == req_normalized:
                continue

            name = os.path.basename(href.rstrip("/"))
            if name in (".", "..", ""):
                continue

            # Extract properties
            prop_el = response_el.find(f".//{_DAV_NS}prop")
            is_dir = False
            size = 0
            content_type = ""
            modified_at = ""

            if prop_el is not None:
                rt = prop_el.find(f"{_DAV_NS}resourcetype")
                if rt is not None and rt.find(f"{_DAV_NS}collection") is not None:
                    is_dir = True

                cl = prop_el.find(f"{_DAV_NS}getcontentlength")
                if cl is not None and cl.text:
                    try:
                        size = int(cl.text)
                    except ValueError:
                        pass

                ct = prop_el.find(f"{_DAV_NS}getcontenttype")
                if ct is not None and ct.text:
                    content_type = ct.text

                lm = prop_el.find(f"{_DAV_NS}getlastmodified")
                if lm is not None and lm.text:
                    modified_at = lm.text

            results.append({
                "href": href,
                "name": name,
                "size": size,
                "content_type": content_type,
                "modified_at": modified_at,
                "is_directory": is_dir,
            })

        return results

    # ── Directory creation ──

    def _ensure_directory(self, path: str) -> None:
        """Recursively create directories via MKCOL."""
        norm = self._normalize(path)
        if not norm or norm == "/":
            return
        parts = [p for p in norm.split("/") if p]
        current = "/"
        for part in parts:
            current = posixpath.join(current, part)
            url = self._build_url_raw(current)
            if not url.endswith("/"):
                url += "/"
            # Check if exists
            resp = self.http.call(
                "PROPFIND", url, direct_response=True,
                headers={"Depth": "0"}, timeout=self._timeout,
            )
            if resp.status_code in (200, 207):
                continue
            # Create
            mk = self.http.call("MKCOL", url, direct_response=True, timeout=self._timeout)
            if mk.status_code not in (201, 405):
                # 405 = already exists on some servers
                mk.raise_for_status()
