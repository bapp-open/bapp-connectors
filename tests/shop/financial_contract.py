"""
Financial capability contract test suite.

Provides a reusable base class that any FinancialCapability adapter must pass.
Subclass FinancialContractTests, implement the `adapter` fixture, and all
contract tests run automatically.

These tests verify the normalized DTO shape across providers — not provider
specific behavior. Every provider that implements FinancialCapability must
produce DTOs with the same structural guarantees.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import FinancialCapability
from bapp_connectors.core.dto import (
    FinancialInvoice,
    FinancialInvoiceLine,
    FinancialTransaction,
    FinancialTransactionType,
    PaginatedResult,
)


class FinancialContractTests:
    """
    Contract tests for FinancialCapability implementations.

    Verifies that get_financial_transactions returns properly shaped DTOs
    regardless of which provider produced them.

    Subclasses MUST provide:
    - `adapter` fixture returning a connected FinancialCapability instance
    - `financial_date_range` fixture returning (start, end) datetime tuple
    - `financial_transaction_type` fixture returning a valid transaction type string for the provider
    """

    @pytest.fixture
    def adapter(self) -> FinancialCapability:
        raise NotImplementedError

    @pytest.fixture
    def financial_date_range(self) -> tuple[datetime, datetime]:
        end = datetime.now(UTC)
        start = end - timedelta(days=30)
        return start, end

    @pytest.fixture
    def financial_transaction_type(self) -> str | None:
        return None

    # ── Capability check ──

    def test_adapter_is_financial_capable(self, adapter):
        assert isinstance(adapter, FinancialCapability)

    # ── get_financial_transactions ──

    def test_returns_paginated_result(self, adapter, financial_date_range, financial_transaction_type):
        start, end = financial_date_range
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
        )
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)
        assert result.total is not None

    def test_transactions_are_financial_dtos(self, adapter, financial_date_range, financial_transaction_type):
        start, end = financial_date_range
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
        )
        for tx in result.items:
            assert isinstance(tx, FinancialTransaction)

    def test_transaction_has_required_fields(self, adapter, financial_date_range, financial_transaction_type):
        start, end = financial_date_range
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
        )
        if not result.items:
            pytest.skip("No transactions in period")
        tx = result.items[0]
        assert tx.transaction_id, "transaction_id must not be empty"
        assert tx.transaction_type in FinancialTransactionType
        assert tx.transaction_date is not None, "transaction_date must be set"

    def test_transaction_amounts_are_decimal(self, adapter, financial_date_range, financial_transaction_type):
        start, end = financial_date_range
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
        )
        if not result.items:
            pytest.skip("No transactions in period")
        tx = result.items[0]
        assert isinstance(tx.debit, Decimal)
        assert isinstance(tx.credit, Decimal)
        assert isinstance(tx.net_amount, Decimal)

    def test_transaction_has_provider_meta(self, adapter, financial_date_range, financial_transaction_type):
        start, end = financial_date_range
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
        )
        if not result.items:
            pytest.skip("No transactions in period")
        tx = result.items[0]
        assert tx.provider_meta is not None
        assert tx.provider_meta.provider, "provider name must not be empty"
        assert tx.provider_meta.raw_payload, "raw_payload must be preserved"

    def test_pagination_cursor(self, adapter, financial_date_range, financial_transaction_type):
        start, end = financial_date_range
        result = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
        )
        if not result.has_more:
            pytest.skip("Only one page of transactions")
        page2 = adapter.get_financial_transactions(
            start_date=start, end_date=end, transaction_type=financial_transaction_type,
            cursor=result.cursor,
        )
        assert isinstance(page2, PaginatedResult)
        assert len(page2.items) > 0


class InvoiceContractTests:
    """
    Contract tests for get_invoices (optional on FinancialCapability).

    Subclasses MUST provide:
    - `adapter` fixture returning a connected FinancialCapability instance
    """

    @pytest.fixture
    def adapter(self) -> FinancialCapability:
        raise NotImplementedError

    def test_returns_paginated_result(self, adapter):
        result = adapter.get_invoices()
        assert isinstance(result, PaginatedResult)
        assert isinstance(result.items, list)

    def test_invoices_are_invoice_dtos(self, adapter):
        result = adapter.get_invoices()
        for inv in result.items:
            assert isinstance(inv, FinancialInvoice)

    def test_invoice_has_required_fields(self, adapter):
        result = adapter.get_invoices()
        if not result.items:
            pytest.skip("No invoices available")
        inv = result.items[0]
        assert inv.invoice_number, "invoice_number must not be empty"
        assert inv.category, "category must not be empty"
        assert inv.date is not None, "date must be set"

    def test_invoice_has_parties(self, adapter):
        result = adapter.get_invoices()
        if not result.items:
            pytest.skip("No invoices available")
        inv = result.items[0]
        assert inv.supplier_name or inv.customer_name, "At least one party must be present"

    def test_invoice_has_lines(self, adapter):
        result = adapter.get_invoices()
        if not result.items:
            pytest.skip("No invoices available")
        inv = result.items[0]
        assert len(inv.lines) > 0, "Invoice must have at least one line"
        line = inv.lines[0]
        assert isinstance(line, FinancialInvoiceLine)
        assert isinstance(line.unit_price, Decimal)
        assert isinstance(line.quantity, Decimal)

    def test_invoice_has_totals(self, adapter):
        result = adapter.get_invoices()
        if not result.items:
            pytest.skip("No invoices available")
        inv = result.items[0]
        assert isinstance(inv.total_amount, Decimal)
        assert isinstance(inv.total_vat, Decimal)
