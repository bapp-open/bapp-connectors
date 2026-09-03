"""Order mapper tests for the bapp_store provider. Pure functions, no network."""
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from importlib.resources import files

from bapp_connectors.core.dto import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from bapp_connectors.providers.shop.bapp_store.mappers import order_from_store, orders_page_from_store

FIXTURES = files("bapp_connectors.providers.shop.bapp_store") / "fixtures"
VAT = Decimal("0.21")


def _export() -> dict:
    return json.loads((FIXTURES / "orders_export.json").read_text())


def test_order_ids_and_status_from_fixture():
    order = order_from_store(_export()["items"][0], VAT)
    assert order.order_id == "ORD-000123"
    assert order.external_id == "ORD-000123"
    assert order.status == OrderStatus.PENDING
    assert order.raw_status == "pending"
    assert order.payment_status == PaymentStatus.UNPAID
    assert order.payment_type == PaymentType.BANK_TRANSFER
    assert order.currency == "RON"
    assert order.created_at == datetime(2026, 9, 2, 14, 5, tzinfo=timezone(timedelta(hours=3)))
    assert order.updated_at == order.created_at
    assert order.external_url == "https://zogjaemtbppsfb0-st.sites.bapp.ro/account/orders/ORD-000123"


def test_order_lines_are_net_with_gross_kept_in_extra():
    order = order_from_store(_export()["items"][0], VAT)
    assert [i.sku for i in order.items] == ["CIO-500", "BAL-60"]
    first, second = order.items
    assert first.product_id == "345100"
    assert first.quantity == Decimal("60")
    assert first.unit_price == Decimal("95.00")
    assert first.currency == "RON"
    assert first.tax_rate == VAT
    assert first.extra["gross_unit_price"] == "114.95"
    assert first.extra["unit_tier"] == "105.75"
    assert first.extra["line_total"] == "6027.75"
    assert second.unit_price == Decimal("66.50")


def test_order_total_is_net_with_gross_and_store_totals_in_extra():
    order = order_from_store(_export()["items"][0], VAT)
    assert order.total == Decimal("8140.56")
    assert order.extra["gross_total"] == "9850.08"
    assert order.extra["goods_total"] == "9850.08"
    assert order.extra["shipping_total"] == "0.00"
    assert order.extra["notes"] == "Livrare dupa ora 10"
    assert order.extra["policy_hash"] == "d781e2f107f3407972917f4a8e84964540086a7f5ad91620de9f4f8536d885b1"
    assert order.extra["volume_discount_total"] == "518.42"
    assert order.extra["value_pct"] == "5.00"


def test_order_billing_contact_carries_company_and_vat_id():
    order = order_from_store(_export()["items"][0], VAT)
    billing = order.billing
    assert billing.name == "Ana Pop"
    assert billing.company_name == "ACME SRL"
    assert billing.vat_id == "RO12345678"
    assert billing.email == "ana@acme.example"
    assert billing.phone == "0712345678"
    assert billing.extra["reg_com"] == "J12/345/2020"
    assert billing.address.street == "Strada Firmei 9"
    assert billing.address.city == "Cluj-Napoca"
    assert billing.address.region == "Cluj"
    assert billing.address.postal_code == "400001"
    assert billing.address.country == "RO"
    assert order.shipping is None
    assert order.shipping_address is None
    assert order.delivery_address == "Strada Firmei 9, Cluj-Napoca, Cluj, 400001"


def test_order_provider_meta_keeps_raw_payload():
    raw = _export()["items"][0]
    order = order_from_store(raw, VAT)
    assert order.provider_meta.provider == "bapp_store"
    assert order.provider_meta.raw_id == "ORD-000123"
    assert order.provider_meta.raw_payload == raw


def test_unknown_status_strings_fall_back_and_are_preserved():
    raw = _export()["items"][0]
    raw = {**raw, "status": "weird", "payment_status": "odd", "payment_type": "voucher"}
    order = order_from_store(raw, VAT)
    assert order.status == OrderStatus.PENDING
    assert order.raw_status == "weird"
    assert order.payment_status == PaymentStatus.UNPAID
    assert order.extra["raw_payment_status"] == "odd"
    assert order.payment_type == PaymentType.OTHER
    assert order.extra["raw_payment_type"] == "voucher"


def test_store_status_aliases():
    raw = _export()["items"][0]
    cases = {
        "confirmed": OrderStatus.ACCEPTED,
        "processing": OrderStatus.PROCESSING,
        "shipped": OrderStatus.SHIPPED,
        "completed": OrderStatus.DELIVERED,
        "delivered": OrderStatus.DELIVERED,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "returned": OrderStatus.RETURNED,
        "refunded": OrderStatus.REFUNDED,
    }
    for store_status, expected in cases.items():
        assert order_from_store({**raw, "status": store_status}, VAT).status == expected, store_status


def test_payment_type_aliases_and_empty():
    raw = _export()["items"][0]
    assert order_from_store({**raw, "payment_type": "card"}, VAT).payment_type == PaymentType.ONLINE_CARD
    assert order_from_store({**raw, "payment_type": "online_card"}, VAT).payment_type == PaymentType.ONLINE_CARD
    assert order_from_store({**raw, "payment_type": "cod"}, VAT).payment_type == PaymentType.CASH_ON_DELIVERY
    assert order_from_store({**raw, "payment_type": "payment_order"}, VAT).payment_type == PaymentType.PAYMENT_ORDER
    assert order_from_store({**raw, "payment_type": ""}, VAT).payment_type is None


def test_orders_page_from_store_maps_pagination():
    page = orders_page_from_store(_export(), VAT)
    assert [o.order_id for o in page.items] == ["ORD-000123"]
    assert page.cursor is None
    assert page.has_more is False

    more = orders_page_from_store({**_export(), "cursor": "ORD-000123", "has_more": True}, VAT)
    assert more.cursor == "ORD-000123"
    assert more.has_more is True


class _FakeClient:
    def __init__(self, export: dict):
        self.export = export
        self.calls: list[tuple] = []

    def export_orders(self, since=None, cursor=None, limit=50):
        self.calls.append(("export_orders", since, cursor, limit))
        return self.export

    def export_order(self, number):
        self.calls.append(("export_order", number))
        return self.export["items"][0]


def _adapter(export: dict) -> tuple[BappStoreShopAdapter, _FakeClient]:
    adapter = BappStoreShopAdapter({"store_url": "https://demo.sites.bapp.ro", "token": "t"}, config={"vat_rate": "0.21"})
    fake = _FakeClient(export)
    adapter.client = fake
    return adapter, fake


def test_get_orders_passes_since_and_cursor_and_maps_page():
    adapter, fake = _adapter(_export())
    page = adapter.get_orders(since=datetime(2026, 9, 1, 12, 0, tzinfo=UTC), cursor="ORD-000100")
    assert fake.calls == [("export_orders", "2026-09-01T12:00:00+00:00", "ORD-000100", 50)]
    assert [o.order_id for o in page.items] == ["ORD-000123"]
    assert page.items[0].items[0].unit_price == Decimal("95.00")
    assert page.has_more is False


def test_get_orders_without_filters_sends_none():
    adapter, fake = _adapter(_export())
    adapter.get_orders()
    assert fake.calls == [("export_orders", None, None, 50)]


def test_get_orders_treats_naive_since_as_utc():
    adapter, fake = _adapter(_export())
    adapter.get_orders(since=datetime(2026, 9, 1, 12, 0))
    assert fake.calls[0][1] == "2026-09-01T12:00:00+00:00"


def test_get_order_maps_single_export():
    adapter, fake = _adapter(_export())
    order = adapter.get_order("ORD-000123")
    assert fake.calls == [("export_order", "ORD-000123")]
    assert order.order_id == "ORD-000123"
    assert order.total == Decimal("8140.56")
