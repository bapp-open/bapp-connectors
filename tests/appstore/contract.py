"""
Contractul AppStorePort — testele pe care le trece orice provider din familia appstore.

Subclasele definesc fixture-urile `adapter`, `sales_window`, `expected_net`, `review_app_id`.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import FinancialCapability
from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    ConnectionTestResult,
    FinancialTransaction,
    FinancialTransactionType,
    PaginatedResult,
)
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.registry import registry
from bapp_connectors.core.types import ProviderFamily


class AppStoreContractTests:
    @pytest.fixture
    def adapter(self) -> AppStorePort:
        raise NotImplementedError

    @pytest.fixture
    def sales_window(self) -> tuple[date, date]:
        raise NotImplementedError

    @pytest.fixture
    def expected_net(self) -> Decimal:
        """Netul asteptat din fixture-ul financiar, pe toata fereastra (suma net_amount)."""
        raise NotImplementedError

    @pytest.fixture
    def review_app_id(self) -> str:
        raise NotImplementedError

    @pytest.fixture
    def unsupported_methods(self) -> set[str]:
        """Metodele optionale (reply_to_review, get_subscription) pe care providerul nu le suporta."""
        return set()

    def test_is_appstore_port(self, adapter):
        assert isinstance(adapter, AppStorePort)
        assert isinstance(adapter, FinancialCapability)

    def test_manifest_valid(self, adapter):
        assert adapter.manifest.validate() == []
        assert adapter.manifest.family == ProviderFamily.APPSTORE

    def test_registered(self, adapter):
        assert registry.is_registered("appstore", adapter.manifest.name)

    def test_declared_capabilities_implemented(self, adapter):
        for capability in adapter.manifest.capabilities:
            assert adapter.supports(capability)

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True

    def test_list_apps(self, adapter):
        apps = adapter.list_apps()
        assert apps and all(isinstance(a, AppStoreApp) for a in apps)

    def _drain(self, fetch, start, end):
        items, cursor, pages = [], None, 0
        while True:
            page = fetch(start, end, cursor)
            assert isinstance(page, PaginatedResult)
            items.extend(page.items)
            pages += 1
            if not page.has_more:
                assert page.cursor is None
                return items, pages
            assert page.cursor
            cursor = page.cursor
            assert pages < 100

    def test_sales_paginate_over_window(self, adapter, sales_window):
        items, pages = self._drain(adapter.get_sales, *sales_window)
        assert items and all(isinstance(s, AppStoreSale) for s in items)
        assert pages >= 1
        assert all(isinstance(s.units, Decimal) for s in items)
        assert all(s.external_key for s in items)

    def test_refunds_are_positive_amounts(self, adapter, sales_window):
        items, _ = self._drain(adapter.list_refunds, *sales_window)
        assert all(isinstance(r, AppStoreRefund) and r.amount >= 0 for r in items)

    def test_financial_transactions_sum_to_expected_net(self, adapter, sales_window, expected_net):
        start, end = sales_window
        items, _ = self._drain(
            lambda s, e, c: adapter.get_financial_transactions(
                datetime.combine(s, time.min), datetime.combine(e, time.max), cursor=c
            ),
            start,
            end,
        )
        assert items and all(isinstance(t, FinancialTransaction) for t in items)
        assert all(t.payout_id for t in items)
        assert all(isinstance(t.net_amount, Decimal) for t in items)
        assert all(t.transaction_type in FinancialTransactionType for t in items)
        assert sum(t.net_amount for t in items) == expected_net

    def test_reviews_paginate(self, adapter, review_app_id):
        page = adapter.list_reviews(review_app_id)
        assert isinstance(page, PaginatedResult)
        assert all(isinstance(r, AppStoreReview) for r in page.items)
        assert all(r.review_id for r in page.items)

    def test_declared_unsupported_methods_raise_not_implemented(self, adapter, review_app_id, unsupported_methods):
        """Metodele declarate nesuportate ridica NotImplementedError; celelalte nu."""
        optional = {
            "reply_to_review": lambda: adapter.reply_to_review(review_app_id, "x", "y"),
            "get_subscription": lambda: adapter.get_subscription("x"),
        }
        for name, call in optional.items():
            if name in unsupported_methods:
                with pytest.raises(NotImplementedError):
                    call()
            else:
                try:
                    call()
                except NotImplementedError:
                    pytest.fail(f"{name} nu e declarata nesuportata, dar ridica NotImplementedError")
                except Exception:
                    pass  # fara raspuns simulat sau eroare de provider: acceptabil
