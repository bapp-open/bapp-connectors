"""bapp_store mapper tests: outbound records must equal the cross-repo fixture samples."""
from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files

import pytest

from bapp_connectors.core.dto import Product, ProductPhoto, ProductUpdate
from bapp_connectors.providers.shop.bapp_store.mappers import (
    category_record,
    html_to_text,
    product_to_record,
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
