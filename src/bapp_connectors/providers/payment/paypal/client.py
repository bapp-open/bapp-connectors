"""
PayPal payment client.

PayPal uses REST API with OAuth2 client credentials for authentication.
Flow: get access token → create order → redirect to approval URL → webhook/capture.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class PayPalApiClient:
    """Low-level PayPal API client."""

    def __init__(self, http_client: ResilientHttpClient, client_id: str, app_secret: str):
        self.http = http_client
        self._client_id = client_id
        self._app_secret = app_secret
        self._access_token: str = ""
        self._token_expires_at: float = 0

    def _get_access_token(self) -> str:
        """Get or refresh OAuth2 access token."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        credentials = base64.b64encode(f"{self._client_id}:{self._app_secret}".encode()).decode()
        response = self.http.call(
            "POST",
            "/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials",
        )
        self._access_token = response["access_token"]
        self._token_expires_at = time.time() + response.get("expires_in", 3600) - 60
        return self._access_token

    def _auth_headers(self) -> dict:
        token = self._get_access_token()
        return {"Authorization": f"Bearer {token}"}

    def create_order(
        self,
        *,
        amount: float,
        currency: str,
        description: str,
        order_id: str,
        return_url: str = "",
        cancel_url: str = "",
    ) -> dict:
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "custom_id": str(order_id),
                    "description": description,
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": f"{amount:.2f}",
                    },
                }
            ],
        }
        if return_url or cancel_url:
            payload["application_context"] = {
                "return_url": return_url,
                "cancel_url": cancel_url,
            }

        return self.http.call(
            "POST", "/v2/checkout/orders",
            headers=self._auth_headers(),
            json=payload,
        )

    def get_order(self, order_id: str) -> dict:
        return self.http.call(
            "GET", f"/v2/checkout/orders/{order_id}",
            headers=self._auth_headers(),
        )

    def capture_order(self, order_id: str) -> dict:
        return self.http.call(
            "POST", f"/v2/checkout/orders/{order_id}/capture",
            headers=self._auth_headers(),
        )

    def create_refund(self, capture_id: str, amount: float | None = None, currency: str = "EUR") -> dict:
        payload: dict[str, Any] = {}
        if amount is not None:
            payload["amount"] = {
                "value": f"{amount:.2f}",
                "currency_code": currency.upper(),
            }
        return self.http.call(
            "POST", f"/v2/payments/captures/{capture_id}/refund",
            headers=self._auth_headers(),
            json=payload,
        )

    def test_auth(self) -> bool:
        """Test authentication by requesting an access token."""
        try:
            self._get_access_token()
            return bool(self._access_token)
        except Exception:
            return False

    # ── Reporting ──

    def list_transactions(
        self,
        *,
        start_date: str,
        end_date: str,
        transaction_type: str | None = None,
        page: int = 1,
        page_size: int = 100,
        fields: str = "all",
    ) -> dict:
        """List transactions from PayPal reporting API.

        Args:
            start_date: ISO 8601 datetime (e.g. "2026-01-01T00:00:00Z").
            end_date: ISO 8601 datetime (e.g. "2026-01-31T23:59:59Z").
            transaction_type: Filter by type (e.g. "T0006" for payouts). Optional.
            page: Page number (1-based).
            page_size: Results per page (max 500).
            fields: "all" or "transaction_info" for minimal response.
        """
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "page": str(page),
            "page_size": str(page_size),
            "fields": fields,
        }
        if transaction_type:
            params["transaction_type"] = transaction_type
        return self.http.call(
            "GET", "/v1/reporting/transactions",
            headers=self._auth_headers(),
            params=params,
        )

    def get_balances(self, currency: str | None = None) -> dict:
        """Get account balances."""
        params: dict[str, Any] = {}
        if currency:
            params["currency_code"] = currency.upper()
        return self.http.call(
            "GET", "/v1/reporting/balances",
            headers=self._auth_headers(),
            params=params,
        )
