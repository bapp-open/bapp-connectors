import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.providers.shop.emag.adapter import EmagShopAdapter
from tests.fake_http import FakeHttpClient

RMA = {
    "emag_id": 7000001, "order_id": "500000001", "request_status": 7, "customer_name": "Client Test",
    "observations": None, "date": "2026-09-21 18:28:55",
    "products": [{"id": 1, "product_id": "81255", "quantity": 1, "product_name": "Suport polita",
                  "return_reason": 51, "observations": "Nu se potriveste pe dimensiune"}],
    "extra_info": {"first_pickup_date": "2026-09-22"},
    "awbs": [{"reservation_id": 481000001}], "courier_name": "sameday",
    "status_history": [
        {"code": "picked_by_courier", "event_date": "2026-09-22 07:22:32"},
        {"code": "refund", "requests": [{"amount": 22.89, "currency": "RON", "refund_type": "CO",
                                          "refund_status": "finalized", "created": "2026-09-22 22:20:15",
                                          "status_date": "2026-09-22 22:31:42"}]},
    ],
    "request_history": [{"date": "21 Sep 2026, 18:29", "user": "System", "action": "creat"}],
}
SINCE = datetime(2026, 9, 20, tzinfo=UTC)
UNTIL = datetime(2026, 9, 24, tzinfo=UTC)


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return EmagShopAdapter(credentials={"username": "u", "password": "p", "country": "RO"}, http_client=fake)


def test_declares_capability():
    from bapp_connectors.providers.shop.emag.manifest import manifest
    assert ReturnsCapability in manifest.capabilities


def test_maps_rma(adapter, fake):
    fake.add("POST", "rma/read", {"isError": False, "results": [RMA]})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert (r.external_id, r.external_order_id, r.status_raw, r.status_label) == ("7000001", "500000001", "7", "Finalized")
    assert r.lines[0].sku == "81255" and r.lines[0].customer_note == "Nu se potriveste pe dimensiune"
    assert r.lines[0].reason_code == "51" and r.lines[0].quantity == Decimal(1)
    assert r.lines[0].reason_label == "Vreau sa returnez un produs functional > Am comandat produsul gresit"
    assert r.comment == "Nu se potriveste pe dimensiune"
    assert r.refund.amount == Decimal("22.89") and r.refund.type == "CO" and r.refund.currency == "RON"
    assert r.awb_ref == "481000001" and r.awb == "" and r.courier == "sameday"
    assert r.picked_up_at is not None and r.requested_at.tzinfo is not None
    assert r.history[0]["user"] == "System"


def test_window_is_sent_in_bucharest_time(adapter, fake):
    fake.add("POST", "rma/read", {"isError": False, "results": []})
    adapter.get_returns(SINCE, UNTIL)
    body = json.loads(fake.last_call().kwargs["data"])
    assert body["date_start"] == "2026-09-20 03:00:00" and body["date_end"] == "2026-09-24 03:00:00"
    assert body["currentPage"] == 1 and body["itemsPerPage"] == 100


def test_paginates_until_short_page(adapter, fake):
    def respond(method, path, kwargs):
        page = json.loads(kwargs["data"])["currentPage"]
        rows = [{**RMA, "emag_id": page * 1000 + i} for i in range(100 if page == 1 else 1)]
        return {"isError": False, "results": rows}
    fake.add("POST", "rma/read", respond)
    assert len(adapter.get_returns(SINCE, UNTIL)) == 101


def test_no_pickup_and_no_refund(adapter, fake):
    rma = {**RMA, "request_status": 3, "extra_info": {"first_pickup_date": None}, "status_history": [], "awbs": []}
    fake.add("POST", "rma/read", {"isError": False, "results": [rma]})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.picked_up_at is None and r.refund is None and r.awb_ref == ""


def test_reason_label_falls_back_to_placeholder_only_when_missing_code(adapter, fake):
    rma = {**RMA, "products": [{**RMA["products"][0], "return_reason": None}]}
    fake.add("POST", "rma/read", {"isError": False, "results": [rma]})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.lines[0].reason_code == "" and r.lines[0].reason_label == ""


def test_resolve_return_awb_handles_dict_results(adapter, fake):
    fake.add("POST", "awb/read", {"isError": False, "results": {"emag_id": 1, "awb": [{"awb_number": "1ONBLR000000001"}]}})
    assert adapter.resolve_return_awb("481000001") == "1ONBLR000000001"
    assert json.loads(fake.last_call().kwargs["data"]) == {"reservation_id": 481000001}


def test_resolve_return_awb_empty_ref_makes_no_call(adapter, fake):
    assert adapter.resolve_return_awb("") == ""
    assert fake.calls == []


# ── get_order_awbs tests (for awb/read dict response) ──

def test_get_order_awbs_nested_object_response(adapter, fake):
    """Test awb/read returns nested object with awb list."""
    fake.add("POST", "awb/read", {
        "isError": False,
        "results": {
            "emag_id": 500000001,
            "order_id": "500000001",
            "reservation_id": 481000001,
            "awb": [
                {"awb_number": "1ONBLR000000001", "awb_barcode": "...", "status": "delivered"},
                {"awb_number": "1ONBLR000000002", "awb_barcode": "...", "status": "picked_up"},
            ],
            "courier": {"courier_name": "sameday", "courier_id": 1},
            "status": {"code": "delivered"},
            "rma_id": None,
            "type": "normal",
        }
    })
    awbs = adapter.get_order_awbs("500000001")
    assert len(awbs) == 2
    assert awbs[0].tracking_number == "1ONBLR000000001"
    assert awbs[1].tracking_number == "1ONBLR000000002"
    assert awbs[0].extra["courier_name"] == "sameday"
    assert awbs[0].extra["emag_id"] == 500000001


def test_get_order_awbs_flat_legacy_response(adapter, fake):
    """Test fallback for flat legacy awb_number at top level."""
    fake.add("POST", "awb/read", {
        "isError": False,
        "results": [
            {
                "awb_number": "1ONBLR000000003",
                "courier_name": "dhl",
                "status": "shipped",
                "type": "normal",
            }
        ]
    })
    awbs = adapter.get_order_awbs("500000001")
    assert len(awbs) == 1
    assert awbs[0].tracking_number == "1ONBLR000000003"
    assert awbs[0].extra["courier_name"] == "dhl"


def test_get_order_awbs_empty_results(adapter, fake):
    """Test empty results returns empty list."""
    fake.add("POST", "awb/read", {"isError": False, "results": {}})
    awbs = adapter.get_order_awbs("500000001")
    assert awbs == []


def test_return_reason_labels_follow_the_documented_hierarchy():
    from bapp_connectors.providers.shop.emag.return_reasons import EMAG_RETURN_REASONS, emag_return_reason_label
    assert len(EMAG_RETURN_REASONS) == 182
    assert emag_return_reason_label(122) == (
        "Vreau sa returnez un produs nefunctional > Produsul este lovit/spart > Ambalajul este intact")
    assert emag_return_reason_label("172").endswith("Am primit un produs cu alte specificatii")
    assert emag_return_reason_label(99999) == "Motiv 99999"
    assert emag_return_reason_label("") == "" and emag_return_reason_label(None) == ""


def test_unified_reason_for_emag_codes():
    from bapp_connectors.core.dto import ReturnReason
    from bapp_connectors.providers.shop.emag.return_reasons import EMAG_RETURN_REASONS, emag_return_reason
    assert emag_return_reason(122) == ReturnReason.DAMAGED        # nefunctional > lovit/spart > ambalaj intact
    assert emag_return_reason(51) == ReturnReason.ORDERED_BY_MISTAKE
    assert emag_return_reason(172) == ReturnReason.NOT_AS_DESCRIBED
    assert emag_return_reason(43) == ReturnReason.WRONG_ITEM
    assert emag_return_reason(99999) == ReturnReason.OTHER
    # "Alt motiv" inherits its parent: nefunctional > Alt motiv = defective
    by_label = {v: k for k, v in EMAG_RETURN_REASONS.items()}
    assert emag_return_reason(by_label["Vreau sa returnez un produs nefunctional > Alt motiv"]) == ReturnReason.DEFECTIVE
    assert emag_return_reason(by_label["Produsul primit prezinta un defect sau este incomplet"]) == ReturnReason.DEFECTIVE
    assert emag_return_reason(by_label["Produsul primit prezinta un defect sau este incomplet > Lipseste un accesoriu"]) == ReturnReason.MISSING_PARTS
    # every documented id resolves to a valid unified reason
    assert all(isinstance(emag_return_reason(k), ReturnReason) for k in EMAG_RETURN_REASONS)


def test_rma_line_carries_the_unified_reason(adapter, fake):
    from bapp_connectors.core.dto import ReturnReason
    fake.add("POST", "rma/read", {"isError": False, "results": [RMA]})
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert r.lines[0].reason == ReturnReason.ORDERED_BY_MISTAKE
