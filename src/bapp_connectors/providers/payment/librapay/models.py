"""Pydantic models for LibraPay API payloads."""

from __future__ import annotations

from pydantic import BaseModel


class LibraPayFormData(BaseModel):
    """Form data sent to LibraPay for payment initiation."""

    AMOUNT: str = ""
    CURRENCY: str = "RON"
    ORDER: str = ""
    DESC: str = ""
    TERMINAL: str = ""
    TIMESTAMP: str = ""
    NONCE: str = ""
    BACKREF: str = ""
    P_SIGN: str = ""


class LibraPayIPNData(BaseModel):
    """IPN notification data received from LibraPay."""

    TERMINAL: str = ""
    TRTYPE: str = ""
    ORDER: str = ""
    AMOUNT: str = ""
    CURRENCY: str = ""
    DESC: str = ""
    ACTION: str = ""
    RC: str = ""  # 00=approved
    MESSAGE: str = ""
    RRN: str = ""
    INT_REF: str = ""
    APPROVAL: str = ""
    TIMESTAMP: str = ""
    NONCE: str = ""
    P_SIGN: str = ""
