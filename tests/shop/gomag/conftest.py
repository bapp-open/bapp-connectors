"""
Shared fixtures for Gomag integration tests.

Run locally:
    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/gomag/ -v -m integration -s
"""

from __future__ import annotations

import os

import pytest

GOMAG_TOKEN = os.environ.get("GOMAG_TOKEN", "")
GOMAG_SHOP_SITE = os.environ.get("GOMAG_SHOP_SITE", "")

skip_unless_gomag = pytest.mark.skipif(
    not all([GOMAG_TOKEN, GOMAG_SHOP_SITE]),
    reason="GOMAG_TOKEN/SHOP_SITE env vars not set. Export them or source .env",
)
