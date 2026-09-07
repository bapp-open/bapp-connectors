"""bapp_store mapper tests: outbound records must equal the cross-repo fixture samples."""
from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files

import pytest

from bapp_connectors.core.dto import OrderValueTier, Product, ProductPhoto, ProductUpdate, ShopRules
from bapp_connectors.providers.shop.bapp_store.mappers import (
    bulk_result_from_response,
    category_from_store,
    category_record,
    html_to_text,
    product_from_store,
    product_to_record,
    rules_to_body,
    update_to_record,
)

FIXTURES = files("bapp_connectors.providers.shop.bapp_store") / "fixtures"


@pytest.fixture(scope="module")
def batch() -> dict:
    return json.loads((FIXTURES / "products_batch.json").read_text())


def _product_from_fixture(record: dict) -> Product:
    """Rebuild the DTO a panel-side consumer would hand the adapter for this fixture record."""
    extra = {
        "bapp": record["extra"]["bapp"],
        "price_tiers": [{"min_quantity": t["min_quantity"], "price": t["price_amount"]} for t in record["price_tiers"]],
    }
    return Product(
        product_id=record["id"],
        sku=record["code"],
        barcode=record["code_ean"] or None,
        name=record["name"],
        description=record["description"],
        price=Decimal("95.00"),  # net PriceCodec value, irrelevant once extra["bapp"] is present
        currency="RON",
        stock=int(record["stock"]),
        active=record["is_active"],
        category_ids=list(record["category_ids"]),
        photos=[ProductPhoto(url=p["url"], position=p["order"]) for p in record.get("photos", [])],
        extra=extra,
    )


@pytest.mark.parametrize("index", [0, 1, 2])
def test_product_to_record_matches_fixture(batch, index):
    expected = batch["request"]["products"][index]
    assert product_to_record(_product_from_fixture(expected)) == expected


def test_product_without_bapp_block_falls_back_to_gross_of_net_price():
    product = Product(product_id="9", name="X", sku="X-1", price=Decimal("100.00"), stock=None)
    record = product_to_record(product, vat_rate=Decimal("0.21"))
    assert record["price"] == {"amount": "121.00", "currency": "RON"}
    assert record["stock"] == "0"
    assert record["extra"] == {}
    assert record["price_tiers"] == []
    assert "photos" not in record
    assert record["primary_category"] is None


def test_product_without_price_omits_price_key():
    record = product_to_record(Product(product_id="9", name="X"))
    assert "price" not in record


def test_update_to_record_full_matches_fixture(batch):
    expected = batch["request"]["products"][0]
    source = _product_from_fixture(expected)
    update = ProductUpdate(
        product_id=source.product_id, sku=source.sku, barcode=source.barcode, name=source.name,
        description=source.description, price=source.price, currency=source.currency, stock=source.stock,
        active=source.active, category_ids=source.category_ids, photos=source.photos, extra=source.extra,
    )
    assert update_to_record(update) == expected


def test_update_to_record_partial_sends_only_set_fields():
    update = ProductUpdate(product_id="345100", stock=3, active=False)
    assert update_to_record(update) == {"id": "345100", "stock": "3", "is_active": False}


def test_update_to_record_empty_tiers_clear_and_empty_categories_clear_primary():
    update = ProductUpdate(product_id="1", category_ids=[], extra={"price_tiers": []})
    record = update_to_record(update)
    assert record["price_tiers"] == []
    assert record["category_ids"] == []
    assert record["primary_category"] is None


def test_update_price_without_bapp_uses_vat_rate():
    record = update_to_record(ProductUpdate(product_id="1", price=Decimal("10.00")), vat_rate=Decimal("0.19"))
    assert record["price"] == {"amount": "11.90", "currency": "RON"}


def test_category_record_matches_fixture(batch):
    expected = batch["request"]["categories"]
    assert category_record("Scule", None, "159") == expected[0]
    assert category_record("Burghie", "159", "160") == expected[1]
    assert category_record("Burghie", "159", "160", is_active=None) == {"id": "160", "parent_id": "159", "name": "Burghie"}


def test_html_to_text_strips_tags_and_keeps_block_breaks():
    html = "<p>Ciocan <b>cu</b> coada.</p><p>Al doilea &amp; ultimul</p>"
    assert html_to_text(html) == "Ciocan cu coada.\nAl doilea & ultimul"


def test_html_to_text_plain_text_passes_through():
    assert html_to_text("Ciocan cu coada de lemn.") == "Ciocan cu coada de lemn."
    assert html_to_text("") == ""


@pytest.fixture(scope="module")
def rules_fixture() -> dict:
    return json.loads((FIXTURES / "rules.json").read_text())


def test_rules_to_body_matches_fixture_and_computes_policy_hash(rules_fixture):
    rules = ShopRules(
        order_value_tiers=[
            OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00")),
            OrderValueTier(min_total=Decimal("10000.00"), discount_percent=Decimal("5.00")),
        ],
        min_order_total=Decimal("1000.00"),
        max_rolling_order_percent=Decimal("6.00"),
        currency="RON",
        extra={"connection_id": 123, "synced_at": "2026-09-02T12:00:00+03:00"},
    )
    assert rules_to_body(rules) == rules_fixture["request"]["rules"]


def test_rules_to_body_without_min_total_hashes_null():
    body = rules_to_body(ShopRules(currency="RON"))
    assert body["min_order_total"] is None
    assert body["order_value_tiers"] == []
    assert len(body["policy_hash"]) == 64


def test_bulk_result_splits_positional_products(batch):
    response = dict(batch["response"])
    response["products"] = [
        {"index": 0, "id": "345100", "status": "created", "error": "", "code": ""},
        {"index": 1, "id": "345101", "status": "error", "error": "unknown category 999", "code": "unknown_category"},
        {"index": 2, "id": "345102", "status": "updated", "error": "", "code": ""},
    ]
    result = bulk_result_from_response(response, 2, 1, ["345100", "345101"], ["345102"])
    assert [i.index for i in result.created] == [0, 1]
    assert result.created[0].remote_id == "345100" and result.created[0].ok
    assert result.created[1].error == "unknown category 999"
    assert result.created[1].error_code == "unknown_category"
    assert [i.index for i in result.updated] == [0]
    assert result.updated[0].remote_id == "345102"
    assert result.failed == 1 and result.succeeded == 2


def test_bulk_result_missing_id_falls_back_to_local_id():
    response = {"products": [{"index": 0, "id": "", "status": "error", "error": "bad", "code": "validation"}]}
    result = bulk_result_from_response(response, 1, 0, ["345100"], [])
    assert result.created[0].remote_id == "345100"


def test_category_from_store_with_expanded_parent():
    row = {"id": 7, "external_id": "160", "name": "Burghie", "is_active": True, "parent": {"id": 5, "external_id": "159", "name": "Scule"}}
    cat = category_from_store(row)
    assert cat.category_id == "160" and cat.parent_id == "159" and cat.name == "Burghie"
    assert cat.extra["store_id"] == "7"


def test_category_from_store_with_bare_parent_pk_and_root():
    assert category_from_store({"id": 7, "external_id": "160", "name": "B", "parent": 5}).parent_id == "5"
    assert category_from_store({"id": 5, "external_id": "159", "name": "S", "parent": None}).parent_id is None


def test_product_from_store_converts_gross_to_net():
    row = {
        "id": 11, "external_id": "345100", "code": "CIO-500", "code_ean": "5941234567890", "name": "Ciocan 500 g",
        "description": "Ciocan cu coada de lemn.", "price_amount": "114.9500", "currency": "RON", "stock_qty": "42.0000", "is_active": True,
    }
    product = product_from_store(row, Decimal("0.21"))
    assert product.product_id == "345100" and product.sku == "CIO-500" and product.barcode == "5941234567890"
    assert product.price == Decimal("95.00")
    assert product.stock == 42 and product.active is True and product.currency == "RON"
    assert product.extra == {"store_id": "11", "gross_price": "114.9500"}


def test_product_from_store_blank_code_is_none():
    row = {"id": 1, "external_id": "2", "code": "", "code_ean": "", "name": "N", "price_amount": "0", "stock_qty": "0"}
    product = product_from_store(row, Decimal("0.21"))
    assert product.sku is None and product.barcode is None and product.price == Decimal("0.00")


def _rules(**kwargs):
    base = {
        "order_value_tiers": [OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00"))],
        "min_order_total": Decimal("1000.00"),
        "currency": "RON",
    }
    return ShopRules(**{**base, **kwargs})


def test_the_rolling_ceiling_reaches_the_body_and_the_hash():
    body = rules_to_body(_rules(max_rolling_order_percent=Decimal("6.00")))
    assert body["max_rolling_order_percent"] == "6.00"
    assert body["policy_hash"] != rules_to_body(_rules())["policy_hash"]


def test_two_rules_that_differ_only_in_the_ceiling_hash_differently():
    a = rules_to_body(_rules(max_rolling_order_percent=Decimal("3.00")))["policy_hash"]
    b = rules_to_body(_rules(max_rolling_order_percent=Decimal("6.00")))["policy_hash"]
    assert a != b
