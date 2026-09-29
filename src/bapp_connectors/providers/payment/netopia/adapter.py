"""
Netopia payment adapter — implements PaymentPort + WebhookCapability.

This is the main entry point for the Netopia integration.
Netopia v2 API with JSON endpoints and API key authentication.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    CheckoutSession,
    ConnectionTestResult,
    PaymentResult,
    Refund,
    WebhookEvent,
)
from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
from bapp_connectors.core.ports import PaymentPort
from bapp_connectors.providers.payment.netopia.client import NetopiaApiClient
from bapp_connectors.providers.payment.netopia.errors import NetopiaOperationError, raise_for_netopia_error
from bapp_connectors.providers.payment.netopia.ipn import (
    NETOPIA_IPN_HEADER,
    NETOPIA_IPN_PUBLIC_KEY,
    NetopiaIpnVerificationError,
    get_header,
    verify_ipn_token,
)
from bapp_connectors.providers.payment.netopia.manifest import (
    NETOPIA_LIVE_URL,
    NETOPIA_SANDBOX_URL,
    manifest,
)
from bapp_connectors.providers.payment.netopia.mappers import (
    checkout_session_from_netopia,
    payment_from_netopia,
    refund_from_netopia,
    webhook_event_from_netopia,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from decimal import Decimal

    from bapp_connectors.core.dto import BillingDetails


class NetopiaPaymentAdapter(PaymentPort, WebhookCapability):
    """
    Netopia payment adapter.

    Implements:
    - PaymentPort: checkout sessions, payment status, refunds
    - WebhookCapability: IPN notification parsing
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.api_key = credentials.get("api_key", "")
        self.pos_signature = credentials.get("pos_signature", "")
        self.sandbox = str(credentials.get("sandbox", "true")).lower() in ("true", "1", "yes")

        base_url = NETOPIA_SANDBOX_URL if self.sandbox else NETOPIA_LIVE_URL

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=MultiHeaderAuth(
                    {
                        "Authorization": self.api_key,
                    }
                ),
                provider_name="netopia",
            )
        else:
            http_client.auth = MultiHeaderAuth(
                {
                    "Authorization": self.api_key,
                }
            )
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = NetopiaApiClient(
            http_client=http_client,
            api_key=self.api_key,
            pos_signature=self.pos_signature,
            sandbox=self.sandbox,
            notify_url=config.get("notify_url", ""),
            redirect_url=config.get("redirect_url", ""),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── PaymentPort ──

    def create_checkout_session(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        identifier: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        client_email: str | None = None,
        billing: BillingDetails | None = None,
    ) -> CheckoutSession:
        _email = (billing.email if billing else None) or client_email or ""
        _phone = billing.phone if billing else ""

        # Extract billing name/address if available
        first_name = ""
        last_name = ""
        city = ""
        address = ""
        if billing:
            # BillingDetails has first/last name and flat address fields; the old
            # `billing.name` / `billing.address` raised AttributeError on any billing.
            first_name = billing.first_name or billing.company
            last_name = billing.last_name
            city = billing.city
            address = ", ".join(x for x in (billing.address_line1, billing.address_line2) if x)

        response = self.client.start_payment(
            amount=float(amount),
            currency=currency,
            description=description,
            order_id=identifier,
            client_email=_email,
            client_phone=_phone,
            first_name=first_name,
            last_name=last_name,
            city=city,
            address=address,
            cancel_url=cancel_url or "",
            success_url=success_url or "",
        )
        raise_for_netopia_error(response, "start payment")
        return checkout_session_from_netopia(response, amount, currency, description)

    def get_payment(self, payment_id: str) -> PaymentResult:
        response = self.client.get_status(ntp_id=payment_id)
        raise_for_netopia_error(response, "status")
        return payment_from_netopia(response)

    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        response = self.client.credit(
            ntp_id=payment_id,
            amount=float(amount) if amount is not None else None,
        )
        raise_for_netopia_error(response, "refund")
        return refund_from_netopia(response, payment_id, requested_amount=amount)

    def cancel_payment(self, payment_id: str) -> PaymentResult:
        """Cancel a payment that has not been captured.

        A pre-authorized payment (status 2) is voided, releasing the hold on the
        card; one never paid is expired. Money already taken cannot be
        cancelled, only refunded.
        """
        current = self.get_payment(payment_id)
        if current.status == "authorized":
            response = self.client.void(ntp_id=payment_id)
            operation = "void"
        elif current.status in ("pending", "processing"):
            response = self.client.expire(ntp_id=payment_id)
            operation = "expire"
        else:
            raise NetopiaOperationError(
                f"Netopia payment {payment_id} is {current.status}; "
                + ("refund it instead." if current.status == "completed" else "nothing to cancel."),
                code=str(current.extra.get("netopia_status_code") or ""),
            )
        raise_for_netopia_error(response, operation)
        return payment_from_netopia(response)

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify a Netopia IPN by its signed ``Verification-Token`` JWT.

        ``secret`` is ignored: Netopia signs with its own key pair. The key is
        Netopia's published one; a ``public_key`` credential, if a connection has
        one, is tried as well (key rotation before a release ships). Fails
        closed — no token or any failed check returns False.
        """
        keys = [NETOPIA_IPN_PUBLIC_KEY]
        if extra := (self.credentials.get("public_key") or "").strip():
            keys.insert(0, extra)
        try:
            verify_ipn_token(get_header(headers, NETOPIA_IPN_HEADER), body, self.pos_signature, keys)
        except NetopiaIpnVerificationError as exc:
            logger.warning("Netopia IPN rejected: %s", exc)
            return False
        except ImportError:
            logger.error("Netopia IPN rejected: the 'cryptography' package is required (bapp-connectors[netopia])")
            return False
        return True

    def webhook_response(self, outcome: str) -> dict:
        """The IPN acknowledgement Netopia expects, as the official plugins send it.

        ``errorType`` drives Netopia's resend: 0 = recorded, 1 = temporary
        (Netopia retries), 2 = permanent (no retry). ``outcome`` is "ok",
        "rejected" (signature failed — retrying cannot help) or "error".
        """
        if outcome == "ok":
            return {"errorType": 0, "errorCode": None, "errorMessage": ""}
        if outcome == "rejected":
            return {"errorType": 2, "errorCode": 0x10000101, "errorMessage": "IPN verification failed"}
        return {"errorType": 1, "errorCode": 1, "errorMessage": "IPN could not be recorded, retry"}

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a Netopia IPN JSON payload into a WebhookEvent."""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            data = {}
        return webhook_event_from_netopia(data)
