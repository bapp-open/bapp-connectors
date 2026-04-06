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


# ── Management API ──

MANAGER_URL = "https://manager.euplatesc.ro/v3/index.php?action=ws"


class EuPlatescApiClient:
    """
    EuPlatesc management API client.

    Uses the manager.euplatesc.ro endpoint for transaction queries,
    invoice listing, captures, refunds, etc.
    All requests are POST with FormData and HMAC-MD5 authentication.
    """

    def __init__(self, http_client, merchant_id: str, merchant_key: bytes, user_key: str = "", user_api: str = ""):
        self.http = http_client
        self._merchant_id = merchant_id
        self._merchant_key = merchant_key
        self._user_key = user_key
        self._user_api = user_api

    def _build_request(self, method: str, extra: dict | None = None) -> dict:
        """Build a signed request for the management API."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        nonce = binascii.b2a_hex(os.urandom(16)).decode()

        data = OrderedDict()
        data["method"] = method
        data["mid"] = self._merchant_id
        data["timestamp"] = timestamp
        data["nonce"] = nonce

        if extra:
            data.update(extra)

        fp_hash = compute_hmac(data, self._merchant_key)
        result = dict(data)
        result["fp_hash"] = fp_hash
        return result

    def _call(self, method: str, extra: dict | None = None) -> dict:
        """Execute a management API call."""
        form_data = self._build_request(method, extra)
        return self.http.call("POST", MANAGER_URL, data=form_data)

    def check_status(self, ep_id: str | None = None, invoice_id: str | None = None) -> dict:
        """Get transaction status by EuPlatesc ID or invoice ID."""
        extra = {}
        if ep_id:
            extra["epid"] = ep_id
        if invoice_id:
            extra["invoice_id"] = invoice_id
        return self._call("CHECK_STATUS", extra)

    def get_invoice_list(self, date_from: str, date_to: str) -> dict:
        """List settlement invoices for a date range.

        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
        """
        return self._call("INVOICES", {
            "ukey": self._user_key,
            "from": date_from,
            "to": date_to,
        })

    def get_invoice_transactions(self, invoice: str) -> dict:
        """Get transactions for a specific settlement invoice.

        Args:
            invoice: Settlement invoice number.
        """
        return self._call("INVOICE", {
            "ukey": self._user_key,
            "invoice": invoice,
        })

    def get_captured_total(self, date_from: str, date_to: str) -> dict:
        """Get total captured amounts for a date range."""
        return self._call("CAPTURED_TOTAL", {
            "ukey": self._user_key,
            "mids": self._merchant_id,
            "from": date_from,
            "to": date_to,
        })

    def check_mid(self) -> dict:
        """Validate merchant ID configuration."""
        return self._call("CHECK_MID")

    def capture(self, ep_id: str) -> dict:
        """Full capture of a pre-authorized transaction."""
        return self._call("CAPTURE", {"ukey": self._user_key, "epid": ep_id})

    def reversal(self, ep_id: str) -> dict:
        """Reverse a transaction."""
        return self._call("REVERSAL", {"ukey": self._user_key, "epid": ep_id})

    def partial_capture(self, ep_id: str, amount: float) -> dict:
        """Partial capture of a pre-authorized transaction."""
        return self._call("PARTIAL_CAPTURE", {
            "ukey": self._user_key,
            "epid": ep_id,
            "amount": f"{amount:.2f}",
        })

    def refund(self, ep_id: str, amount: float, reason: str = "") -> dict:
        """Full or partial refund."""
        extra = {
            "ukey": self._user_key,
            "epid": ep_id,
            "amount": f"{amount:.2f}",
        }
        if reason:
            extra["reason"] = reason
        return self._call("REFUND", extra)

    def get_saved_cards(self, client_id: str) -> dict:
        """Get saved cards for a client."""
        return self._call("C2P_CARDS", {"c2p_id": client_id})

    def remove_card(self, client_id: str, card_id: str) -> dict:
        """Remove a saved card."""
        return self._call("C2P_DELETE", {"c2p_id": client_id, "c2p_cid": card_id})
