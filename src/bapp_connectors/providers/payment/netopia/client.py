"""
Netopia API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient for retry, rate limiting, and error handling.
Netopia v2 uses a JSON API with API key authentication.
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

    def _json_post(self, path: str, payload: dict) -> dict | list | str:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._call("POST", path, data=data)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by calling the health endpoint."""
        try:
            result = self._call("GET", "healz")
            return result == "ok" or (isinstance(result, dict) and not result.get("error"))
        except Exception:
            return False

    # ── Payment: Card ──

    def start_payment(
        self,
        *,
        amount: float,
        currency: str,
        description: str,
        order_id: str,
        client_email: str = "",
        client_phone: str = "",
        first_name: str = "",
        last_name: str = "",
        city: str = "",
        country: int = 642,
        country_name: str = "Romania",
        state: str = "",
        postal_code: str = "",
        address: str = "",
        cancel_url: str = "",
        success_url: str = "",
        notify_url: str = "",
        products: list[dict] | None = None,
        instrument: dict | None = None,
        browser_data: dict | None = None,
    ) -> dict:
        """Start a card payment. Returns payment response with paymentURL."""
        payload: dict[str, Any] = {
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
                "instrument": instrument,
                "data": browser_data or {},
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
                    "firstName": first_name,
                    "lastName": last_name,
                    "city": city,
                    "country": country,
                    "countryName": country_name,
                    "state": state,
                    "postalCode": postal_code,
                    "details": address,
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
                "products": products or [],
                "installments": {"selected": 0, "available": []},
                "data": {},
            },
        }

        return self._json_post("payment/card/start", payload)

    def verify_auth(self, authentication_token: str, ntp_id: str, form_data: dict | None = None) -> dict:
        """Complete 3-D Secure authentication."""
        payload: dict[str, Any] = {
            "authenticationToken": authentication_token,
            "ntpID": ntp_id,
        }
        if form_data:
            payload["formData"] = form_data
        return self._json_post("payment/card/verify-auth", payload)

    # ── Payment: BNPL ──

    def start_bnpl_payment(self, **kwargs) -> dict:
        """Start a Buy Now Pay Later payment. Same payload as card start."""
        # Build the same payload as start_payment
        payload = self._build_start_payload(**kwargs)
        return self._json_post("payment/bnpl/start", payload)

    def bnpl_return(self, ntp_id: str) -> dict:
        """Handle BNPL return."""
        return self._json_post("payment/bnpl/return", {"ntpID": ntp_id})

    # ── Payment: Apple Pay ──

    def applepay_merchant_check(self, **kwargs) -> dict:
        """Validate merchant for Apple Pay."""
        return self._json_post("payment/applepay/merchant-check", kwargs)

    # ── Operations ──

    def get_status(self, ntp_id: str | None = None, order_id: str | None = None) -> dict:
        """Get payment status by NTP ID or order ID."""
        payload: dict[str, Any] = {}
        if ntp_id:
            payload["ntpID"] = ntp_id
        if order_id:
            payload["orderID"] = order_id
        return self._json_post("operation/status", payload)

    def capture(self, ntp_id: str, amount: float | None = None) -> dict:
        """Capture a pre-authorized payment (full or partial)."""
        payload: dict[str, Any] = {"ntpID": ntp_id}
        if amount is not None:
            payload["amount"] = amount
        return self._json_post("operation/capture", payload)

    def void(self, ntp_id: str) -> dict:
        """Void/cancel a pre-authorized payment."""
        return self._json_post("operation/void", {"ntpID": ntp_id})

    def credit(self, ntp_id: str, amount: float | None = None) -> dict:
        """Refund a payment (full or partial)."""
        payload: dict[str, Any] = {"ntpID": ntp_id}
        if amount is not None:
            payload["amount"] = amount
        return self._json_post("operation/credit", payload)

    def expire(self, ntp_id: str) -> dict:
        """Expire a pending payment."""
        return self._json_post("operation/expire", {"ntpID": ntp_id})

    def get_payment_options(self, ntp_id: str, instrument: dict | None = None) -> dict:
        """Get available installments and loyalty points for a payment."""
        payload: dict[str, Any] = {"ntpID": ntp_id}
        if instrument:
            payload["instrument"] = instrument
        return self._json_post("operation/payment-options", payload)

    # ── Internal helpers ──

    def _build_start_payload(self, **kwargs) -> dict:
        """Build the start payment payload (shared between card and BNPL)."""
        return {
            "config": {
                "emailTemplate": "default",
                "emailSubject": "",
                "cancelUrl": kwargs.get("cancel_url", ""),
                "notifyUrl": kwargs.get("notify_url", "") or self.notify_url,
                "redirectUrl": kwargs.get("success_url", "") or self.redirect_url,
                "language": "ro",
            },
            "payment": {
                "options": {"installments": 0, "bonus": 0},
                "instrument": kwargs.get("instrument"),
                "data": kwargs.get("browser_data", {}),
            },
            "order": {
                "ntpID": None,
                "posSignature": self.pos_signature,
                "dateTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "orderID": kwargs.get("order_id", ""),
                "description": str(kwargs.get("description", "")),
                "amount": float(kwargs.get("amount", 0)),
                "currency": (kwargs.get("currency") or "RON").upper(),
                "billing": {
                    "email": kwargs.get("client_email", ""),
                    "phone": kwargs.get("client_phone", ""),
                    "firstName": kwargs.get("first_name", ""),
                    "lastName": kwargs.get("last_name", ""),
                    "city": kwargs.get("city", ""),
                    "country": kwargs.get("country", 642),
                    "countryName": kwargs.get("country_name", "Romania"),
                    "state": kwargs.get("state", ""),
                    "postalCode": kwargs.get("postal_code", ""),
                    "details": kwargs.get("address", ""),
                },
                "shipping": {
                    "email": "", "phone": "", "firstName": "", "lastName": "",
                    "city": "", "country": 0, "countryName": "", "state": "",
                    "postalCode": "", "details": "",
                },
                "products": kwargs.get("products", []),
                "installments": {"selected": 0, "available": []},
                "data": {},
            },
        }
