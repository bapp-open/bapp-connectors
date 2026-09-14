"""Pure mapper tests — no Docker, no network."""
from decimal import Decimal

from bapp_connectors.core.dto import Product, ProductPhoto, ProductUpdate
from bapp_connectors.providers.shop.woocommerce.mappers import (
    product_to_woocommerce,
    product_update_to_woocommerce,
)


def test_create_payload_uses_category_ids_not_names():
    product = Product(product_id="1", name="Ciocan", categories=["Scule"], category_ids=["12", "7"])
    data = product_to_woocommerce(product)
    assert data["categories"] == [{"id": 12}, {"id": 7}]


def test_create_payload_without_category_ids_sends_no_categories():
    product = Product(product_id="1", name="Ciocan", categories=["Scule"])
    assert "categories" not in product_to_woocommerce(product)


def test_update_payload_category_ids_none_leaves_categories_untouched():
    update = ProductUpdate(product_id="5", name="X")
    assert "categories" not in product_update_to_woocommerce(update)


def test_update_payload_empty_category_ids_clears_categories():
    update = ProductUpdate(product_id="5", category_ids=[])
    assert product_update_to_woocommerce(update)["categories"] == []


def test_update_payload_maps_price_and_photos():
    update = ProductUpdate(
        product_id="5", price=Decimal("10.00"),
        photos=[ProductPhoto(url="https://cdn/x.jpg", position=0, alt_text="x")],
    )
    data = product_update_to_woocommerce(update, price_to_provider=lambda p: p * Decimal("1.19"))
    assert data["regular_price"] == "11.9000"
    assert data["images"] == [{"src": "https://cdn/x.jpg", "alt": "x", "position": 0}]


def test_billing_vat_id_comes_from_woo_meta_data():
    """WooCommerce nu are camp standard de CUI: pluginurile romanesti il pun in
    meta_data (_billing_company_vat_id si variante). Fara el, o comanda de firma
    nu poate fi legata de partenerul corect si se cade pe potriviri slabe."""
    from bapp_connectors.providers.shop.woocommerce.mappers import order_from_woocommerce

    order = order_from_woocommerce({
        "id": 34436,
        "number": "34436",
        "status": "processing",
        "currency": "RON",
        "total": "2476.23",
        "billing": {
            "company": "ALFAN COM S.R.L.",
            "first_name": "DUMITRU", "last_name": "PREDICA",
            "email": "client@example.com", "phone": "+40765599447",
        },
        "meta_data": [
            {"key": "is_vat_exempt", "value": "no"},
            {"key": "_billing_company_vat_id", "value": "4253111"},
        ],
        "line_items": [],
    })
    assert order.billing.vat_id == "4253111"
    assert order.billing.company_name == "ALFAN COM S.R.L."


def test_billing_vat_id_accepts_the_other_plugin_keys():
    from bapp_connectors.providers.shop.woocommerce.mappers import order_from_woocommerce

    for key in ("_billing_cif", "billing_cui", "_billing_vat_number"):
        order = order_from_woocommerce({
            "id": 1, "number": "1", "status": "processing", "currency": "RON", "total": "1",
            "billing": {"company": "X SRL"},
            "meta_data": [{"key": key, "value": "RO123456"}],
            "line_items": [],
        })
        assert order.billing.vat_id == "RO123456", key


def test_a_vat_id_that_is_really_a_name_is_ignored():
    """Camp completat gresit de client: daca nu contine cifre, nu e CUI."""
    from bapp_connectors.providers.shop.woocommerce.mappers import order_from_woocommerce

    order = order_from_woocommerce({
        "id": 2, "number": "2", "status": "processing", "currency": "RON", "total": "1",
        "billing": {"company": "INSTANT INTERNATIONAL SRL"},
        "meta_data": [{"key": "_billing_company_vat_id", "value": "INSTANT INTERNATIONAL SRL"}],
        "line_items": [],
    })
    assert order.billing.vat_id == ""
