"""Temu request signing.

API calls: ``sign = MD5(app_secret + Σ(key + value, keys sorted ASCII) + app_secret)``, hex
uppercase. Non-string values are serialised as compact JSON (``separators=(",", ":")``,
``ensure_ascii=False``) exactly as they are sent in the body. Signed documents (shipping labels)
use the same scheme over five ``toa-*`` headers.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def sign_params(app_secret: str, params: dict) -> str:
    """MD5 signature of ``params`` (an existing ``sign`` key is ignored)."""
    body = "".join(f"{key}{_value_text(params[key])}" for key in sorted(params) if key != "sign")
    return hashlib.md5(f"{app_secret}{body}{app_secret}".encode()).hexdigest().upper()


def signed_document_headers(
    app_key: str,
    app_secret: str,
    access_token: str,
    *,
    timestamp: int | None = None,
    random_digits: str | None = None,
) -> dict:
    """Headers for downloading a signed Temu document URL (label PDF, report file)."""
    params = {
        "toa-app-key": app_key,
        "toa-access-token": access_token,
        "toa-random": random_digits or "".join(secrets.choice("0123456789") for _ in range(32)),
        "toa-timestamp": str(timestamp if timestamp is not None else int(time.time())),
    }
    return {**params, "toa-sign": sign_params(app_secret, params)}
