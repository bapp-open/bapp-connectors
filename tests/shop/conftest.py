"""
Shared fixtures for shop integration tests.

WooCommerce requires WordPress + MySQL via docker-compose.test.yml.
"""

from __future__ import annotations

import os
import socket

import pytest

# ── Service addresses ──

WOO_HOST = os.environ.get("WOO_HOST", "127.0.0.1")
WOO_PORT = int(os.environ.get("WOO_PORT", "8888"))

# Known test API keys (created by scripts/setup_woocommerce.py)
WOO_CONSUMER_KEY = os.environ.get("WOO_CONSUMER_KEY", "ck_testkey123456789")
WOO_CONSUMER_SECRET = os.environ.get("WOO_CONSUMER_SECRET", "cs_testsecret123456789")


def _is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False


skip_unless_woo = pytest.mark.skipif(
    not _is_port_open(WOO_HOST, WOO_PORT),
    reason=f"WooCommerce not reachable at {WOO_HOST}:{WOO_PORT}. Run: docker compose -f docker-compose.test.yml up -d",
)

# ── PrestaShop ──

PS_HOST = os.environ.get("PS_HOST", "127.0.0.1")
PS_PORT = int(os.environ.get("PS_PORT", "8889"))
PS_API_KEY = os.environ.get("PS_API_KEY", "TESTKEY123456789ABCDEFGHIJKLMNOP")

skip_unless_prestashop = pytest.mark.skipif(
    not _is_port_open(PS_HOST, PS_PORT),
    reason=f"PrestaShop not reachable at {PS_HOST}:{PS_PORT}. Run: docker compose -f docker-compose.test.yml up -d",
)

# ── Magento ──

MG_HOST = os.environ.get("MG_HOST", "127.0.0.1")
MG_PORT = int(os.environ.get("MG_PORT", "8890"))
MG_ACCESS_TOKEN = os.environ.get("MG_ACCESS_TOKEN", "")

skip_unless_magento = pytest.mark.skipif(
    not _is_port_open(MG_HOST, MG_PORT),
    reason=f"Magento not reachable at {MG_HOST}:{MG_PORT}. Run: docker compose -f docker-compose.test.yml up -d",
)
