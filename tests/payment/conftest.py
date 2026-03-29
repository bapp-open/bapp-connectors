"""
Shared fixtures for payment integration tests.

External payment APIs (Stripe, etc.) are gated by environment variables
rather than Docker port checks.

Run locally:
    STRIPE_SECRET_KEY=sk_test_... uv run --extra dev pytest tests/payment/ -v -m integration
"""

from __future__ import annotations

import os
import shutil

import pytest

# ── Stripe ──

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

skip_unless_stripe = pytest.mark.skipif(
    not STRIPE_SECRET_KEY,
    reason="STRIPE_SECRET_KEY env var not set. Provide a sk_test_... key to run Stripe integration tests.",
)

skip_unless_stripe_cli = pytest.mark.skipif(
    not STRIPE_SECRET_KEY or not shutil.which("stripe"),
    reason="Stripe CLI not installed or STRIPE_SECRET_KEY not set.",
)
