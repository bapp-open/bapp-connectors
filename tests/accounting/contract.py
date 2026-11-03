"""Reusable contract tests every accounting provider must pass."""

from datetime import date

import pytest

from bapp_connectors.core.dto import ImportResult
from bapp_connectors.core.ports import AccountingPort, BasePort


class AccountingContractTests:
    @pytest.fixture
    def accounting_adapter(self) -> AccountingPort:
        raise NotImplementedError("provider tests must supply an accounting_adapter fixture")

    def test_is_accounting_port(self, accounting_adapter):
        assert isinstance(accounting_adapter, AccountingPort)
        assert isinstance(accounting_adapter, BasePort)

    def test_validate_credentials(self, accounting_adapter):
        assert accounting_adapter.validate_credentials() is True

    def test_test_connection(self, accounting_adapter):
        assert accounting_adapter.test_connection().success is True

    def test_import_file_returns_import_result(self, accounting_adapter):
        result = accounting_adapter.import_file("F_1_1_01_01_2026.xml", b"<Facturi/>")
        assert isinstance(result, ImportResult)

    def test_stock_report_is_list(self, accounting_adapter):
        assert isinstance(accounting_adapter.get_stock_report(date(2026, 1, 1), date(2026, 1, 31)), list)
