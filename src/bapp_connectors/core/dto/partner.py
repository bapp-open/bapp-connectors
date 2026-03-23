"""
Normalized DTOs for contacts and addresses.
"""

from __future__ import annotations

from .base import BaseDTO


class Address(BaseDTO):
    """Normalized postal address."""

    street: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""  # ISO 3166-1 alpha-2
    extra: dict = {}


class Contact(BaseDTO):
    """Normalized contact information."""

    name: str = ""
    company_name: str = ""
    vat_id: str = ""
    email: str = ""
    phone: str = ""
    address: Address | None = None
    extra: dict = {}
