"""
Financial capability — optional interface for providers that expose financial data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.base import PaginatedResult
    from bapp_connectors.core.dto.financial import FinancialInvoice, FinancialTransaction


class FinancialCapability(ABC):
    """Adapter supports reading financial transactions and invoices."""

    @abstractmethod
    def get_financial_transactions(
        self,
        start_date: datetime,
        end_date: datetime,
        transaction_type: str | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[FinancialTransaction]:
        """Fetch financial transactions (settlements, commissions, payouts).

        Args:
            start_date: Start of date range.
            end_date: End of date range.
            transaction_type: Provider-specific filter (e.g. "Sale", "Return", "PaymentOrder").
            cursor: Pagination cursor.
        """
        ...

    def get_invoices(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category: str | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[FinancialInvoice]:
        """Fetch marketplace invoices (commission invoices, settlements).

        Args:
            start_date: Start of date range.
            end_date: End of date range.
            category: Invoice category filter.
            cursor: Pagination cursor.
        """
        raise NotImplementedError("This provider does not support invoice retrieval.")
