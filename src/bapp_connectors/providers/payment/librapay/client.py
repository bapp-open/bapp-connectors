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

import base64
import binascii
import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Field limits from the LibraPay implementation manual (IV.1).
MAX_DESC_LENGTH = 50
MAX_BACKREF_LENGTH = 80

COUNTRY_NAMES = {"RO": "Romania"}


def generate_order_id() -> str:
    """A fresh LibraPay ORDER: 6-19 digits, unique per order, no leading zero.

    Milliseconds since the epoch (13 digits, never starting with 0) plus six
    random digits — 19, the most LibraPay allows — so checkouts started in the
    same millisecond still differ.
    """
    return f"{int(time.time() * 1000)}{secrets.randbelow(1_000_000):06d}"


def build_data_custom(
    amount: float,
    description: str,
    email: str = "",
    name: str = "",
    phone: str = "",
    city: str = "",
    country: str = "",
    address: str = "",
    tax_id: str = "",
) -> str:
    """DATA_CUSTOM: base64 of the ProductsData + UserData the manual marks mandatory.

    The manual shows PHP ``serialize``; phclient has sent JSON in production
    for years and LibraPay accepts it, so JSON it is (no PHP serializer needed).
    """
    country_name = COUNTRY_NAMES.get((country or "RO").upper(), country) or "Romania"
    user = {
        "Email": email,
        "Name": name,
        "Phone": phone,
        "BillingEmail": email,
        "BillingName": name,
        "BillingPhone": phone,
        "BillingCity": city,
        "BillingCountry": country_name,
        "BillingAddress": address,
        "BillingID": tax_id,
        "ShippingEmail": email,
        "ShippingName": name,
        "ShippingAddress": address,
        "ShippingPhone": phone,
        "ShippingCity": city,
        "ShippingCountry": country_name,
    }
    data = {
        "ProductsData": {0: {"ItemName": description[:MAX_DESC_LENGTH], "Quantity": 1, "Price": f"{amount:.2f}"}},
        "UserData": user,
    }
    return base64.b64encode(json.dumps(data).encode()).decode()


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
    data_custom: str = "",
) -> dict:
    """Build LibraPay checkout form data with HMAC-SHA1 signature.

    ``order_id`` must already be LibraPay's numeric ORDER (``generate_order_id``);
    ``description`` is cut to the 50 characters LibraPay allows.
    """
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
    nonce = binascii.b2a_hex(os.urandom(16)).decode()

    data = OrderedDict([
        ("AMOUNT", f"{amount:.2f}"),
        ("CURRENCY", currency),
        ("ORDER", order_id),
        ("DESC", description[:MAX_DESC_LENGTH]),
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
        "DATA_CUSTOM": data_custom,
        "P_SIGN": p_sign,
    }
    return result
