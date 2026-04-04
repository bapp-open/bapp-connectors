"""
Shared fixtures for LLM integration tests.

Run locally:
    set -a && source .env && set +a
    uv run --extra dev pytest tests/llm/ -v -m integration
"""

from __future__ import annotations

import os

import pytest

# ── LLM integration test credentials (from .env or environment) ──

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ── Markers ──

skip_unless_gemini = pytest.mark.skipif(
    not GEMINI_API_KEY,
    reason="GEMINI_API_KEY env var not set. Export it or source .env",
)
