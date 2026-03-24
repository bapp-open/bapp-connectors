"""
EuPlatesc payment client.

EuPlatesc uses a form-based payment flow:
1. Build form data with HMAC-MD5 signature → redirect customer to EuPlatesc
2. EuPlatesc POSTs IPN notification to your server with payment result

There's no REST API for querying payments — all communication is via form POST + IPN.
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
    """Encode a value in EuPlatesc's HMAC format: length + value."""
    if isinstance(val, bytes):
        val = val.decode()
    else:
        val = str(val)
    return f"{len(val.encode())}{val}"


def compute_hmac(data: OrderedDict, merchant_key: bytes) -> str:
    """Compute EuPlatesc HMAC-MD5 hash for form data."""
    hash_str = ""
    for value in data.values():
        hash_str += _enc(value)
    return hmac.new(merchant_key, hash_str.encode(), hashlib.md5).hexdigest()


def verify_ipn_hmac(post_data: dict, merchant_key: bytes) -> bool:
    """Verify an EuPlatesc IPN HMAC-MD5 signature.

    The IPN POST contains an fp_hash field. We rebuild the hash from the other
    fields in the expected order and compare.
    """
    ipn_fields = [
        "amount", "curr", "invoice_id", "ep_id", "merch_id",
        "action", "message", "approval", "timestamp", "nonce",
    ]
    hash_str = ""
    ipn_hash = post_data.get("fp_hash", "")

    for field in ipn_fields:
        value = post_data.get(field, "")
        if not value:
            hash_str += "-"
        else:
            hash_str += _enc(value)

    # sec_status is optional — only include if present
    if "sec_status" in post_data:
        sec_status = post_data["sec_status"]
        if not sec_status:
            hash_str += "-"
        else:
            hash_str += _enc(sec_status)

    digest = hmac.new(merchant_key, hash_str.encode(), hashlib.md5).hexdigest()
    return digest.upper() == ipn_hash.upper()


def build_checkout_form(
    amount: float,
    currency: str,
    invoice_id: str,
    description: str,
    merchant_id: str,
    merchant_key: bytes,
    back_url: str = "",
    client_data: dict | None = None,
) -> dict:
    """Build the EuPlatesc checkout form data with HMAC signature.

    Returns a dict with all form fields including fp_hash.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    nonce = binascii.b2a_hex(os.urandom(24)).decode()

    data = OrderedDict([
        ("amount", str(round(amount, 2))),
        ("curr", currency),
        ("invoice_id", invoice_id),
        ("order_desc", description),
        ("merch_id", merchant_id),
        ("timestamp", timestamp),
        ("nonce", nonce),
    ])

    fp_hash = compute_hmac(data, merchant_key)
    result = dict(data)
    result["fp_hash"] = fp_hash

    # Optional client data (not included in HMAC)
    if client_data:
        result.update(client_data)
    if back_url:
        result["backurl"] = back_url

    return result


# ── IPN status codes ──

SEC_STATUS_MAP = {
    "1": "valid_not_finished",
    "2": "failed",
    "3": "manual_verification",
    "4": "waiting_response",
    "5": "possible_fraud",
    "6": "shipping_not_allowed",
    "7": "pickup_in_store",
    "8": "authenticated_ok",
    "9": "verified_ok",
}
