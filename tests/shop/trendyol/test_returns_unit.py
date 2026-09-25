from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.providers.shop.trendyol.adapter import TrendyolShopAdapter
from tests.fake_http import FakeHttpClient


def _unit(status, note=""):
    return {"id": f"u-{status}-{note}", "orderLineItemId": 1, "claimItemStatus": {"name": status},
            "customerClaimItemReason": {"id": 551, "name": "Too big", "code": "BIGSIZE"}, "customerNote": note}


def _claim(units, claim_id="c-1", awb=5000000001):
    return {
        "claimId": claim_id, "orderNumber": "11500000001", "claimDate": 1789502148014,
        "customerFirstName": "Ana ", "customerLastName": "Test", "cargoTrackingNumber": awb,
        "cargoProviderName": "FANEX", "cargoTrackingLink": "https://tracking.example/x",
        "items": [{"orderLine": {"id": 77, "productName": "Roata", "barcode": "6420000000001",
                                  "merchantSku": "157269", "price": 59.27}, "claimItems": units}],
    }


SINCE = datetime(2026, 9, 10, tzinfo=UTC)
UNTIL = datetime(2026, 9, 24, tzinfo=UTC)


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return TrendyolShopAdapter(credentials={"seller_id": "123", "username": "u", "password": "p", "country": "RO"}, http_client=fake)


def test_declares_capability():
    from bapp_connectors.providers.shop.trendyol.manifest import manifest
    assert ReturnsCapability in manifest.capabilities


def test_maps_claim(adapter, fake):
    fake.add("GET", "claims", {"content": [_claim([_unit("WaitingInAction", "Nu se potriveste")])], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert (r.external_id, r.external_order_id, r.status_raw) == ("c-1", "11500000001", "WaitingInAction")
    assert r.customer_name == "Ana Test" and r.awb == "5000000001" and r.courier == "FANEX"
    assert r.tracking_url == "https://tracking.example/x"
    line = r.lines[0]
    assert (line.sku, line.barcode, line.quantity, line.unit_price) == ("157269", "6420000000001", Decimal(1), Decimal("59.27"))
    assert line.reason_code == "BIGSIZE" and line.customer_note == "Nu se potriveste" and r.comment == "Nu se potriveste"
    assert r.refund is None and r.requested_at.tzinfo is not None
    params = fake.last_call().kwargs["params"]
    assert params["startDate"] == int(SINCE.timestamp() * 1000) and params["page"] == 0


def test_quantity_is_number_of_units_and_least_advanced_wins(adapter, fake):
    fake.add("GET", "claims", {"content": [_claim([_unit("Accepted"), _unit("Created")])], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.lines[0].quantity == Decimal(2) and r.status_raw == "Created"
    assert r.lines[0].unit_statuses == ["Accepted", "Created"]


def test_cancelled_units_ignored_unless_all_cancelled(adapter, fake):
    fake.add("GET", "claims", {"content": [_claim([_unit("Cancelled"), _unit("Accepted")], "c-1"),
                                           _claim([_unit("Cancelled")], "c-2")], "totalPages": 1})
    first, second = adapter.get_returns(SINCE, UNTIL)
    assert first.status_raw == "Accepted" and second.status_raw == "Cancelled"


def test_quantity_counts_non_cancelled_units_only(adapter, fake):
    # 2 units total, 1 Cancelled -> quantity is the 1 live unit, not len(units).
    fake.add("GET", "claims", {"content": [_claim([_unit("Cancelled"), _unit("Accepted")])], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.lines[0].quantity == Decimal(1)


def test_quantity_falls_back_to_unit_count_when_all_cancelled(adapter, fake):
    fake.add("GET", "claims", {"content": [_claim([_unit("Cancelled"), _unit("Cancelled")])], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.lines[0].quantity == Decimal(2)


def test_estimated_refund_for_accepted_units(adapter, fake):
    fake.add("GET", "claims", {"content": [_claim([_unit("Accepted"), _unit("Accepted")])], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.refund.amount == Decimal("118.54") and r.refund.estimated is True and r.refund.currency == "RON"


def test_paginates(adapter, fake):
    def respond(method, path, kwargs):
        page = kwargs["params"]["page"]
        return {"content": [_claim([_unit("Created")], f"c-{page}")], "totalPages": 2}
    fake.add("GET", "claims", respond)
    assert [r.external_id for r in adapter.get_returns(SINCE, UNTIL)] == ["c-0", "c-1"]


def test_claim_without_awb(adapter, fake):
    fake.add("GET", "claims", {"content": [_claim([_unit("Created")], awb=None)], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.awb == ""


def test_empty_window_with_null_content(adapter, fake):
    # Trendyol answers an empty window with {"content": null, "totalElements": 0}
    fake.add("GET", "claims", {"content": None, "page": 0, "size": 0, "totalElements": 0, "totalPages": 0})
    assert adapter.get_returns(SINCE, UNTIL) == []


def test_unified_reason_from_customer_code(adapter, fake):
    from bapp_connectors.core.dto import ReturnReason
    from bapp_connectors.providers.shop.trendyol.mappers import trendyol_return_reason
    fake.add("GET", "claims", {"content": [_claim([_unit("Accepted")])], "totalPages": 1})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.lines[0].reason == ReturnReason.SIZE_FIT  # BIGSIZE
    assert trendyol_return_reason("UNDELIVERED") == ReturnReason.NOT_DELIVERED
    assert trendyol_return_reason("DAMAGEDITEM") == ReturnReason.DAMAGED
    assert trendyol_return_reason("NONPUNITIVEAPPROVAL") == ReturnReason.OTHER
    assert trendyol_return_reason(None) == ReturnReason.OTHER
