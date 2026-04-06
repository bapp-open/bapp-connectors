"""
Shared fixtures for Trendyol integration tests.

Run locally:
    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/trendyol/ -v -m integration -s
"""

from __future__ import annotations

import os

import pytest

TRENDYOL_USERNAME = os.environ.get("TRENDYOL_USERNAME", "")
TRENDYOL_PASSWORD = os.environ.get("TRENDYOL_PASSWORD", "")
TRENDYOL_SELLER_ID = os.environ.get("TRENDYOL_SELLER_ID", "")
TRENDYOL_COUNTRY = os.environ.get("TRENDYOL_COUNTRY", "RO")

skip_unless_trendyol = pytest.mark.skipif(
    not all([TRENDYOL_USERNAME, TRENDYOL_PASSWORD, TRENDYOL_SELLER_ID]),
    reason="TRENDYOL_USERNAME/PASSWORD/SELLER_ID env vars not set. Export them or source .env",
)
