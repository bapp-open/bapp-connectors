"""
Cardinity payment client.

Cardinity uses form-based checkout with HMAC-SHA256 signatures.
Flow: build form → POST to Cardinity → customer pays → POST back with status.
"""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(fields: dict, project_secret: str) -> str:
    """Compute Cardinity HMAC-SHA256 signature over sorted form fields.

    Signature string is built by sorting field keys alphabetically and
    concatenating key+value pairs.
    """
    sorted_keys = sorted(fields.keys())
    signature_string = ""
    for key in sorted_keys:
        signature_string += str(key) + str(fields[key])
    return hmac.new(
        project_secret.encode(),
        signature_string.encode(),
        hashlib.sha256,
    ).hexdigest()


def build_checkout_form(
    amount: float,
    currency: str,
    order_id: str,
    description: str,
    project_key: str,
    project_secret: str,
    return_url: str,
    cancel_url: str,
    country: str = "LT",
) -> dict:
    """Build Cardinity checkout form data with HMAC-SHA256 signature."""
    fields = {
        "amount": f"{amount:.2f}",
        "cancel_url": cancel_url,
        "country": country.upper(),
        "currency": currency.upper(),
        "description": description,
        "order_id": str(order_id),
        "project_id": project_key,
        "return_url": return_url,
    }

    signature = compute_signature(fields, project_secret)

    return {
        **fields,
        "signature": signature,
    }
