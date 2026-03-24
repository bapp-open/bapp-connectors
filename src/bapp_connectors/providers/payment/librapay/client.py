"""
LibraPay payment client.

LibraPay uses form-based checkout with HMAC-SHA1 signatures.
Flow: build form → POST to LibraPay → customer pays → IPN POST back.

Key differences from EuPlatesc:
- HMAC-SHA1 (not MD5)
- P_SIGN field (not fp_hash)
- Uppercase field names (AMOUNT, CURRENCY, ORDER, etc.)
- Uses MERCHANT, TERMINAL, MERCH_NAME, MERCH_URL, EMAIL fields
- IPN response code: RC=00 means approved
"""

from __future__ import annotations

import binascii
import datetime
import hashlib
import hmac
import logging
import os
from collections import OrderedDict

logger = logging.getLogger(__name__)


def _enc(val) -> str:
    """Encode a value in LibraPay's HMAC format: length + value, or '-' for None/empty."""
    if val is None:
        return "-"
    if isinstance(val, bytes):
        val = val.decode()
    else:
        val = str(val)
    return f"{len(val.encode())}{val}"


def compute_hmac(data: OrderedDict, key: bytes) -> str:
    """Compute LibraPay HMAC-SHA1 hash for form data."""
    hash_str = ""
    for val in data.values():
        hash_str += _enc(val)
    return hmac.new(key, hash_str.encode(), hashlib.sha1).hexdigest().upper()


def verify_ipn_hmac(post_data: dict, key: bytes) -> bool:
    """Verify a LibraPay IPN HMAC-SHA1 signature.

    The IPN contains P_SIGN. We rebuild the hash from the other fields.
    """
    ipn_fields = [
        "TERMINAL", "TRTYPE", "ORDER", "AMOUNT", "CURRENCY",
        "DESC", "ACTION", "RC", "MESSAGE", "RRN",
        "INT_REF", "APPROVAL", "TIMESTAMP", "NONCE",
    ]
    hash_str = ""
    ipn_hash = post_data.get("P_SIGN", "")

    for field in ipn_fields:
        value = post_data.get(field, "")
        if not value:
            hash_str += "-"
        else:
            hash_str += _enc(value)

    digest = hmac.new(key, hash_str.encode(), hashlib.sha1).hexdigest()
    return digest.upper() == ipn_hash.upper()


def build_checkout_form(
    amount: float,
    currency: str,
    order_id: str,
    description: str,
    merchant: str,
    terminal: str,
    merchant_name: str,
    merchant_url: str,
    merchant_email: str,
    key: bytes,
    back_url: str = "",
) -> dict:
    """Build LibraPay checkout form data with HMAC-SHA1 signature."""
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
    nonce = binascii.b2a_hex(os.urandom(16)).decode()

    data = OrderedDict([
        ("AMOUNT", f"{amount:.2f}"),
        ("CURRENCY", currency),
        ("ORDER", order_id),
        ("DESC", description),
        ("MERCH_NAME", merchant_name),
        ("MERCH_URL", merchant_url),
        ("MERCHANT", merchant),
        ("TERMINAL", terminal),
        ("EMAIL", merchant_email),
        ("TRTYPE", "0"),
        ("COUNTRY", None),
        ("MERCH_GMT", None),
        ("TIMESTAMP", timestamp),
        ("NONCE", nonce),
        ("BACKREF", back_url),
    ])

    p_sign = compute_hmac(data, key)

    # Only include fields that LibraPay expects in the form
    result = {
        "AMOUNT": data["AMOUNT"],
        "CURRENCY": data["CURRENCY"],
        "ORDER": data["ORDER"],
        "DESC": data["DESC"],
        "TERMINAL": data["TERMINAL"],
        "TIMESTAMP": data["TIMESTAMP"],
        "NONCE": data["NONCE"],
        "BACKREF": back_url,
        "P_SIGN": p_sign,
    }
    return result
