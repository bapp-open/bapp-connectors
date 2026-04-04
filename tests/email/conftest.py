"""
Shared fixtures for email integration tests.

Run locally:
    set -a && source .env && set +a
    uv run --extra dev pytest tests/email/ -v -m integration
"""

from __future__ import annotations

import os
import socket

import pytest

# ── Email integration test credentials (from .env or environment) ──

EMAIL_TEST_USER = os.environ.get("EMAIL_TEST_USER", "")
EMAIL_TEST_PASSWORD = os.environ.get("EMAIL_TEST_PASSWORD", "")
EMAIL_TEST_RECIPIENT = os.environ.get("EMAIL_TEST_RECIPIENT", "")
EMAIL_TEST_SMTP_HOST = os.environ.get("EMAIL_TEST_SMTP_HOST", "")
EMAIL_TEST_SMTP_PORT = int(os.environ.get("EMAIL_TEST_SMTP_PORT", "587"))
EMAIL_TEST_IMAP_HOST = os.environ.get("EMAIL_TEST_IMAP_HOST", "")
EMAIL_TEST_IMAP_PORT = int(os.environ.get("EMAIL_TEST_IMAP_PORT", "993"))

# ── MailHog (Docker) ──

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
        reason=f"{name} not reachable at {host}:{port}.",
    )


# ── Markers ──

skip_unless_mailhog = skip_unless_service(MAILHOG_HOST, MAILHOG_SMTP_PORT, "MailHog")

skip_unless_email = pytest.mark.skipif(
    not EMAIL_TEST_USER or not EMAIL_TEST_SMTP_HOST,
    reason="EMAIL_TEST_* env vars not set. Export them or source .env",
)
