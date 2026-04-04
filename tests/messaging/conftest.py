"""
Shared fixtures for messaging integration tests.

These tests require running Docker services (see docker-compose.test.yml).
They are marked with @pytest.mark.integration and skipped by default.

Run locally:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev pytest tests/messaging/ -v -m integration
"""

from __future__ import annotations

import os
import socket

import pytest

# ── Service addresses (env vars for CI, defaults for local Docker) ──

MAILHOG_HOST = os.environ.get("MAILHOG_HOST", "127.0.0.1")
MAILHOG_SMTP_PORT = int(os.environ.get("MAILHOG_SMTP_PORT", "1025"))
MAILHOG_API_PORT = int(os.environ.get("MAILHOG_API_PORT", "8025"))


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

skip_unless_mailhog = skip_unless_service(MAILHOG_HOST, MAILHOG_SMTP_PORT, "MailHog")
