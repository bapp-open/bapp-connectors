"""Pydantic models for EuPlatesc API payloads."""

from __future__ import annotations

from pydantic import BaseModel


class EuPlatescFormData(BaseModel):
    """Form data sent to EuPlatesc for payment initiation."""

    amount: str = ""
    curr: str = "RON"
    invoice_id: str = ""
    order_desc: str = ""
    merch_id: str = ""
    timestamp: str = ""
    nonce: str = ""
    fp_hash: str = ""
    # Optional client data
    fname: str = ""
    lname: str = ""
    company: str = ""
    add: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    phone: str = ""
    email: str = ""
    lang: str = "ro"
    backurl: str = ""


class EuPlatescIPNData(BaseModel):
    """IPN notification data received from EuPlatesc."""

    amount: str = ""
    curr: str = ""
    invoice_id: str = ""
    ep_id: str = ""
    merch_id: str = ""
    action: str = ""  # 0=approved, 1+=error codes
    message: str = ""
    approval: str = ""
    timestamp: str = ""
    nonce: str = ""
    fp_hash: str = ""
    sec_status: str = ""
