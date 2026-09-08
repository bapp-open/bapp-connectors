"""WooCommerce adapter tests against FakeHttpClient — no Docker."""
from __future__ import annotations

import pytest

from bapp_connectors.core.dto import ProductCategory
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from tests.fake_http import FakeHttpClient


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    # No domain => the adapter keeps the injected http client instead of building a real one.
    return WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"}, http_client=fake)


def test_update_category_puts_name_and_parent(adapter, fake):
    fake.add("PUT", "products/categories/7", {"id": 7, "name": "Scule electrice", "parent": 3})
    result = adapter.update_category(ProductCategory(category_id="7", name="Scule electrice", parent_id="3"))
    assert result.category_id == "7"
    assert result.parent_id == "3"
    call = fake.last_call()
    assert call.method == "PUT" and call.path == "products/categories/7"
    assert call.kwargs["json"] == {"name": "Scule electrice", "parent": 3}


def test_update_category_root_sends_parent_zero(adapter, fake):
    fake.add("PUT", "products/categories/7", {"id": 7, "name": "Scule", "parent": 0})
    result = adapter.update_category(ProductCategory(category_id="7", name="Scule"))
    assert fake.last_call().kwargs["json"] == {"name": "Scule", "parent": 0}
    assert result.parent_id is None


def test_find_product_by_sku_returns_product(adapter, fake):
    fake.add("GET", "products", [{"id": 55, "sku": "AB-1", "name": "Ciocan", "price": "10", "status": "publish"}])
    product = adapter.find_product_by_sku("AB-1")
    assert product is not None and product.product_id == "55"
    assert fake.last_call().kwargs["params"]["sku"] == "AB-1"
    assert fake.last_call().kwargs["params"]["per_page"] == 1


def test_find_product_by_sku_empty_list_is_none(adapter, fake):
    fake.add("GET", "products", [])
    assert adapter.find_product_by_sku("NOPE") is None


def test_find_product_by_sku_blank_sku_short_circuits(adapter, fake):
    assert adapter.find_product_by_sku("") is None
    assert fake.calls == []


def test_woocommerce_declares_lookup_capability():
    from bapp_connectors.core.capabilities import ProductLookupCapability
    from bapp_connectors.providers.shop.woocommerce.manifest import manifest

    assert ProductLookupCapability in manifest.capabilities


def test_bulk_upsert_sends_create_and_update_and_maps_positionally(adapter, fake):
    from decimal import Decimal

    from bapp_connectors.core.dto import Product, ProductUpdate

    fake.add("POST", "products/batch", {
        "create": [
            {"id": 101, "sku": "A", "date_modified_gmt": "2026-08-31T10:00:00"},
            {"id": 0, "error": {"code": "product_invalid_sku", "message": "SKU exists", "data": {"resource_id": 77, "unique_sku": "B"}}},
        ],
        "update": [{"id": 9, "date_modified_gmt": "2026-08-31T10:00:01"}],
    })
    result = adapter.bulk_upsert_products(
        creates=[Product(product_id="a", sku="A", name="A", price=Decimal("1")), Product(product_id="b", sku="B", name="B")],
        updates=[ProductUpdate(product_id="9", name="Nine")],
    )
    payload = fake.last_call().kwargs["json"]
    assert [c["sku"] for c in payload["create"]] == ["A", "B"]
    assert payload["update"] == [{"id": 9, "name": "Nine"}]
    assert result.created[0].remote_id == "101"
    assert result.created[0].extra["date_modified_gmt"] == "2026-08-31T10:00:00"
    assert result.created[1].error_code == "product_invalid_sku"
    assert result.created[1].extra["resource_id"] == 77
    assert result.updated[0].remote_id == "9"
    assert result.failed == 1


def test_bulk_upsert_empty_input_makes_no_call(adapter, fake):
    result = adapter.bulk_upsert_products(creates=[], updates=[])
    assert result.created == [] and result.updated == [] and fake.calls == []


def test_bulk_upsert_rejects_more_than_max_batch(adapter):
    from bapp_connectors.core.dto import Product

    creates = [Product(product_id=str(i), name=str(i)) for i in range(101)]
    with pytest.raises(ValueError):
        adapter.bulk_upsert_products(creates=creates, updates=[])


def test_get_products_since_sends_modified_after_gmt(adapter, fake):
    from datetime import UTC, datetime

    fake.add("GET", "products", [])
    adapter.get_products(cursor="2", since=datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC))
    params = fake.last_call().kwargs["params"]
    assert params["page"] == 2
    assert params["modified_after"] == "2026-08-30T12:00:00"
    assert params["dates_are_gmt"] == "true"
    assert params["orderby"] == "modified" and params["order"] == "asc"


def test_get_products_without_since_keeps_default_ordering(adapter, fake):
    fake.add("GET", "products", [])
    adapter.get_products()
    params = fake.last_call().kwargs["params"]
    assert "modified_after" not in params and params["orderby"] == "date"


def test_bulk_upsert_is_never_retried_and_has_a_long_read_timeout(adapter, fake):
    from bapp_connectors.core.dto import Product

    fake.add("POST", "products/batch", {"create": [{"id": 1}]})
    adapter.bulk_upsert_products(creates=[Product(product_id="a", sku="A", name="A")], updates=[])
    kwargs = fake.last_call().kwargs
    assert kwargs["retry"] is False
    assert kwargs["timeout"][1] >= 120


def test_create_product_is_never_retried(adapter, fake):
    from bapp_connectors.core.dto import Product

    fake.add("POST", "products", {"id": 5, "name": "A"})
    adapter.create_product(Product(product_id="a", sku="A", name="A"))
    assert fake.last_call().kwargs["retry"] is False


# ── Settings detection (prices_include_vat / vat_rate from the store itself) ──


def test_detect_settings_reads_tax_options_and_standard_rate(adapter, fake):
    fake.add("GET", "settings/tax", [
        {"id": "woocommerce_prices_include_tax", "value": "yes"},
        {"id": "woocommerce_calc_taxes", "value": "yes"},
    ])
    fake.add("GET", "taxes", [
        {"id": 1, "rate": "19.0000", "class": "standard", "country": "RO"},
        {"id": 2, "rate": "9.0000", "class": "reduced-rate", "country": "RO"},
    ])
    detected = adapter.detect_settings()
    assert detected == {"prices_include_vat": True, "vat_rate": "0.19"}


def test_detect_settings_prices_entered_without_tax(adapter, fake):
    fake.add("GET", "settings/tax", [
        {"id": "woocommerce_prices_include_tax", "value": "no"},
        {"id": "woocommerce_calc_taxes", "value": "yes"},
    ])
    fake.add("GET", "taxes", [])
    assert adapter.detect_settings() == {"prices_include_vat": False}


def test_detect_settings_taxes_disabled_means_final_prices(adapter, fake):
    # cu taxele oprite, pretul introdus e pretul final -> il tratam ca brut,
    # indiferent ce scrie in optiunea prices_include_tax
    fake.add("GET", "settings/tax", [
        {"id": "woocommerce_prices_include_tax", "value": "no"},
        {"id": "woocommerce_calc_taxes", "value": "no"},
    ])
    fake.add("GET", "taxes", [])
    assert adapter.detect_settings() == {"prices_include_vat": True}


def test_detect_settings_unreadable_endpoints_returns_empty(adapter, fake):
    # FakeHttpClient arunca la orice ruta nemapata: detectia nu are voie sa explodeze
    assert adapter.detect_settings() == {}


def test_woocommerce_declares_settings_detection_capability():
    from bapp_connectors.core.capabilities import SettingsDetectionCapability
    from bapp_connectors.providers.shop.woocommerce.manifest import manifest

    assert SettingsDetectionCapability in manifest.capabilities
