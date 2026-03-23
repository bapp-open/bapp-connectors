"""
Shared fixtures for storage integration tests.

These tests require running Docker services (see docker-compose.test.yml).
They are marked with @pytest.mark.integration and skipped by default.

Run locally:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev --extra sftp --extra s3 pytest tests/storage/ -v -m integration

In CI (GitLab), services run as sidecars and are accessible by hostname.
Configure via environment variables:
    MINIO_HOST, MINIO_PORT, FTP_HOST, FTP_PORT, SFTP_HOST, SFTP_PORT, WEBDAV_HOST, WEBDAV_PORT
"""

from __future__ import annotations

import os
import socket

import pytest

# ── Service addresses (env vars for CI, defaults for local Docker) ──

MINIO_HOST = os.environ.get("MINIO_HOST", "127.0.0.1")
MINIO_PORT = int(os.environ.get("MINIO_PORT", "19000"))
FTP_HOST = os.environ.get("FTP_HOST", "127.0.0.1")
FTP_PORT = int(os.environ.get("FTP_PORT", "2121"))
SFTP_HOST = os.environ.get("SFTP_HOST", "127.0.0.1")
SFTP_PORT = int(os.environ.get("SFTP_PORT", "2222"))
WEBDAV_HOST = os.environ.get("WEBDAV_HOST", "127.0.0.1")
WEBDAV_PORT = int(os.environ.get("WEBDAV_PORT", "8080"))


def _is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def skip_unless_service(host: str, port: int, name: str):
    """Return a pytest skip marker if the service is not reachable."""
    return pytest.mark.skipif(
        not _is_port_open(host, port),
        reason=f"{name} not reachable at {host}:{port}. Run: docker compose -f docker-compose.test.yml up -d",
    )


# ── Markers ──

skip_unless_minio = skip_unless_service(MINIO_HOST, MINIO_PORT, "MinIO")
skip_unless_ftp = skip_unless_service(FTP_HOST, FTP_PORT, "FTP")
skip_unless_sftp = skip_unless_service(SFTP_HOST, SFTP_PORT, "SFTP")
skip_unless_webdav = skip_unless_service(WEBDAV_HOST, WEBDAV_PORT, "WebDAV")
