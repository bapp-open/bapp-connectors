"""
Normalized DTOs for financial transactions (settlements, invoices, commissions).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO, ProviderMeta


class FinancialTransactionType(StrEnum):
    """Normalized financial transaction types across providers."""

    SALE = "sale"
    RETURN = "return"
    COMMISSION = "commission"
    PAYMENT = "payment"
    DEDUCTION = "deduction"
    CREDIT_NOTE = "credit_note"
    REFUND = "refund"
    OTHER = "other"


class FinancialTransaction(BaseDTO):
    """Normalized financial transaction across marketplace providers."""

    transaction_id: str = ""
    transaction_type: FinancialTransactionType = FinancialTransactionType.OTHER
    raw_transaction_type: str = ""
    transaction_date: datetime | None = None
    description: str = ""
    currency: str = ""

    # Amounts
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")

    # Commission
    commission_rate: Decimal | None = None
    commission_amount: Decimal | None = None

    # Order reference
    order_id: str = ""
    invoice_number: str = ""

    # Payment
    payment_date: datetime | None = None

    # Provider metadata
    provider_meta: ProviderMeta | None = None
    extra: dict = {}


class FinancialInvoice(BaseDTO):
    """Normalized marketplace invoice (commission invoice, settlement, etc.)."""

    invoice_id: str = ""
    invoice_number: str = ""
    category: str = ""
    date: datetime | None = None
    is_storno: bool = False
    reversal_for: str = ""
    currency: str = ""

    # Parties
    supplier_name: str = ""
    supplier_tax_id: str = ""
    customer_name: str = ""
    customer_tax_id: str = ""

    # Totals
    total_amount: Decimal = Decimal("0")
    total_vat: Decimal = Decimal("0")

    # Line items
    lines: list[FinancialInvoiceLine] = []

    # Order reference (for customer invoices)
    order_id: str = ""

    provider_meta: ProviderMeta | None = None
    extra: dict = {}


class FinancialInvoiceLine(BaseDTO):
    """Line item within a financial invoice."""

    description: str = ""
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    vat_rate: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    unit_of_measure: str = ""
