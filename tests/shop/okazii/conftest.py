"""
Shared fixtures for Okazii integration tests.

Run locally:
    set -a && source .env && set +a
    uv run --extra dev pytest tests/shop/okazii/ -v -m integration -s
"""

from __future__ import annotations

import os

import pytest

OKAZII_TOKEN = os.environ.get("OKAZII_TOKEN", "")

skip_unless_okazii = pytest.mark.skipif(
    not OKAZII_TOKEN,
    reason="OKAZII_TOKEN env var not set. Export it or source .env",
)
