"""
Shared fixtures for eMAG integration tests.

Run locally:
    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/emag/ -v -m integration -s
"""

from __future__ import annotations

import os

import pytest

EMAG_USERNAME = os.environ.get("EMAG_USERNAME", "")
EMAG_PASSWORD = os.environ.get("EMAG_PASSWORD", "")
EMAG_COUNTRY = os.environ.get("EMAG_COUNTRY", "RO")

skip_unless_emag = pytest.mark.skipif(
    not all([EMAG_USERNAME, EMAG_PASSWORD]),
    reason="EMAG_USERNAME/PASSWORD env vars not set. Export them or source .env",
)
