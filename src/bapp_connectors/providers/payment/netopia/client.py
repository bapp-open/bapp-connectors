"""
Netopia API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient for retry, rate limiting, and error handling.
Netopia uses a JSON API with API key + POS signature authentication.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class NetopiaApiClient:
    """
    Low-level Netopia API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        api_key: str,
        pos_signature: str,
        sandbox: bool = True,
        notify_url: str = "",
        redirect_url: str = "",
    ):
        self.http = http_client
        self.api_key = api_key
        self.pos_signature = pos_signature
        self.sandbox = sandbox
        self.notify_url = notify_url
        self.redirect_url = redirect_url

        self._extra_headers = {
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, **kwargs: Any) -> dict | list | str:
        headers = dict(self._extra_headers)
        if extra := kwargs.pop("headers", None):
            headers.update(extra)
        return self.http.call(method, path, headers=headers, **kwargs)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """
        Verify credentials by attempting a minimal start payment call.

        Netopia does not have a dedicated auth-test endpoint, so we verify
        that the API key is accepted. A validation error (not auth error)
        means credentials are valid.
        """
        try:
            self.start_payment(
                amount=0.01,
                currency="RON",
                description="Connection test",
                order_id="test-connection",
            )
            return True
        except Exception:
            # Any response that is not an auth error means credentials work
            return False

    # ── Payment Operations ──

    def start_payment(
        self,
        *,
        amount: float,
        currency: str,
        description: str,
        order_id: str,
        client_email: str = "",
        client_phone: str = "",
        cancel_url: str = "",
        success_url: str = "",
        notify_url: str = "",
    ) -> dict:
        """Start a Netopia payment. Returns the payment response with paymentURL."""
        payload = {
            "config": {
                "emailTemplate": "default",
                "emailSubject": "",
                "cancelUrl": cancel_url,
                "notifyUrl": notify_url or self.notify_url,
                "redirectUrl": success_url or self.redirect_url,
                "language": "ro",
            },
            "payment": {
                "options": {"installments": 0, "bonus": 0},
                "instrument": None,
                "data": {},
            },
            "order": {
                "ntpID": None,
                "posSignature": self.pos_signature,
                "dateTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "orderID": order_id,
                "description": str(description),
                "amount": float(amount),
                "currency": currency.upper() if currency else "RON",
                "billing": {
                    "email": client_email,
                    "phone": client_phone,
                    "firstName": "",
                    "lastName": "",
                    "city": "",
                    "country": 1,
                    "countryName": "Romania",
                    "state": "",
                    "postalCode": "",
                    "details": "",
                },
                "shipping": {
                    "email": "",
                    "phone": "",
                    "firstName": "",
                    "lastName": "",
                    "city": "",
                    "country": 0,
                    "countryName": "",
                    "state": "",
                    "postalCode": "",
                    "details": "",
                },
                "products": [],
                "installments": {"selected": 0, "available": []},
                "data": {},
            },
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._call("POST", "payment/card/start", data=data)

    def get_status(self, ntp_id: str) -> dict:
        """Get the status of a Netopia payment by NTP ID."""
        payload = {
            "ntpID": ntp_id,
            "posSignature": self.pos_signature,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._call("POST", "payment/status", data=data)
