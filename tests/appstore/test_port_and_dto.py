"""Portul AppStorePort si DTO-urile familiei appstore."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStorePlatform,
    AppStoreProductType,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    PaginatedResult,
    WebhookEventType,
)
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.types import ProviderFamily
from bapp_connectors.core.webhooks import ADAPTER_VERIFIED_METHODS


def test_family_exists():
    assert ProviderFamily.APPSTORE == "appstore"


def test_sale_dto_is_frozen_and_decimal():
    sale = AppStoreSale(
        external_key="k1",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 1),
        sku="com.cbsoft.pro",
        units=Decimal("2"),
        proceeds_unit=Decimal("3.50"),
        proceeds_total=Decimal("7.00"),
        product_type=AppStoreProductType.IAP,
    )
    assert sale.proceeds_total == Decimal("7.00")
    assert sale.is_refund is False
    with pytest.raises(ValidationError):
        sale.units = Decimal("3")  # frozen


def test_review_rating_optional_for_steam():
    review = AppStoreReview(review_id="r1", recommended=True)
    assert review.rating is None
    assert review.recommended is True


def test_app_and_refund_defaults():
    app = AppStoreApp(app_id="123", platform=AppStorePlatform.APPLE)
    assert app.bundle_id == ""
    refund = AppStoreRefund(refund_id="x")
    assert refund.amount == Decimal("0")


def test_webhook_event_types_added():
    assert WebhookEventType.SUBSCRIPTION_RENEWED == "subscription.renewed"
    assert WebhookEventType.SUBSCRIPTION_EXPIRED == "subscription.expired"
    assert WebhookEventType.PURCHASE_REFUNDED == "purchase.refunded"


def test_adapter_verified_methods_include_appstore():
    assert "apple-jws" in ADAPTER_VERIFIED_METHODS
    assert "google-pubsub-oidc" in ADAPTER_VERIFIED_METHODS


class _Minimal(AppStorePort):
    """Implementeaza doar metodele abstracte; restul trebuie sa ridice NotImplementedError."""

    manifest = None

    def validate_credentials(self):
        return True

    def test_connection(self):
        raise AssertionError("neapelat")

    def list_apps(self):
        return []

    def get_sales(self, start, end, cursor=None):
        return PaginatedResult(items=[])

    def list_refunds(self, start, end, cursor=None):
        return PaginatedResult(items=[])

    def list_reviews(self, app_id, since=None, cursor=None):
        return PaginatedResult(items=[])


def test_port_optional_methods_raise_not_implemented():
    port = _Minimal()
    with pytest.raises(NotImplementedError):
        port.reply_to_review("a", "r", "text")
    with pytest.raises(NotImplementedError):
        port.get_subscription("ref")
