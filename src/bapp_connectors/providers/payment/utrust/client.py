"""
Utrust payment client.

Utrust uses a REST JSON API for order creation and HMAC-SHA256 for webhook verification.
Flow: create order via API → redirect customer → webhook POST on payment.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


def sort_payload(payload: dict, prefix: str = "") -> str:
    """Recursively sort payload by keys and concatenate key+value pairs."""
    result = ""
    for key in sorted(payload.keys()):
        val = payload[key]
        if isinstance(val, dict):
            result += sort_payload(val, prefix=key)
        else:
            result += f"{prefix}{key}{val}"
    return result


def verify_hmac(payload: dict, webhook_secret: str) -> bool:
    """Verify Utrust webhook HMAC-SHA256 signature.

    The signature is extracted from the payload and verified against
    the recursively sorted remaining fields.
    """
    payload = dict(payload)  # don't mutate the original
    signature = payload.pop("signature", "")
    if not signature:
        return False
    sorted_data = sort_payload(payload)
    digest = hmac.new(
        webhook_secret.encode(),
        sorted_data.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


class UtrustApiClient:
    """Low-level Utrust API client."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def create_order(
        self,
        *,
        reference: str,
        amount: float,
        currency: str,
        description: str,
        return_url: str,
        cancel_url: str,
        callback_url: str,
        customer_email: str = "",
        customer_first_name: str = "",
        customer_last_name: str = "",
        customer_country: str = "",
    ) -> dict:
        payload: dict[str, Any] = {
            "data": {
                "type": "orders",
                "attributes": {
                    "order": {
                        "reference": str(reference),
                        "amount": {
                            "total": f"{amount:.2f}",
                            "currency": currency.upper(),
                        },
                        "return_urls": {
                            "return_url": return_url,
                            "cancel_url": cancel_url,
                            "callback_url": callback_url,
                        },
                        "line_items": [
                            {
                                "name": description,
                                "price": f"{amount:.2f}",
                                "currency": currency.upper(),
                                "quantity": 1,
                            }
                        ],
                    },
                    "customer": {
                        "first_name": customer_first_name,
                        "last_name": customer_last_name,
                        "email": customer_email,
                        "country": customer_country,
                    },
                },
            }
        }
        return self.http.post("/stores/orders", json=payload)
