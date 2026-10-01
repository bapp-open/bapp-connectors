"""Categoriile unui produs Magento: ID-uri în `category_ids`, nu doar în `categories`.

Aceeași nepotrivire pe care am găsit-o la PrestaShop pe un magazin real: DTO-ul are două
câmpuri — `categories` (NUME, așa le umple WooCommerce) și `category_ids` (ID-uri) — iar
aplicația gazdă (`company_product/shop_sync`) mapează categoria citind `category_ids`. Magento
punea ID-urile doar în `categories`, deci la preluare produsele veneau fără categorie, iar la
trimitere mapper-ul citea `categories` în timp ce gazda completează `category_ids`.

Fără un Magento de test (imaginea `bitnami/magento` a dispărut de pe Docker Hub, iar varianta
oficială cere chei Adobe), payload-ul de aici e forma documentată a REST API-ului 2.4:
`extension_attributes.category_links[].category_id`, exact ce citea deja mapper-ul.
"""

from bapp_connectors.core.dto import Product as ProductDTO
from bapp_connectors.providers.shop.magento.mappers import (
    product_from_magento,
    product_to_magento,
)

PRODUCT = {
    "id": 12,
    "sku": "SKU-1",
    "name": "Lanternă",
    "status": 1,
    "price": "99.90",
    "extension_attributes": {
        "stock_item": {"qty": 7},
        "category_links": [
            {"position": 0, "category_id": "11"},
            {"position": 1, "category_id": "23"},
        ],
    },
}


def test_the_ids_land_in_category_ids():
    product = product_from_magento(PRODUCT)
    assert product.category_ids == ["11", "23"]


def test_the_old_field_keeps_its_value():
    """Codul care citea id-ul din `categories` nu se rupe."""
    assert product_from_magento(PRODUCT).categories == ["11", "23"]


def test_a_product_without_categories_has_neither():
    product = product_from_magento({"id": 1, "sku": "X", "status": 1, "extension_attributes": {}})
    assert product.category_ids == [] and product.categories == []


def test_pushing_reads_the_ids_the_host_sends():
    """Gazda completeaza `category_ids`; mapper-ul citea doar `categories`."""
    payload = product_to_magento(ProductDTO(product_id="1", sku="S", name="X", category_ids=["42"]))
    links = payload["extension_attributes"]["category_links"]
    assert [row["category_id"] for row in links] == ["42"]


def test_pushing_still_honours_the_old_field():
    payload = product_to_magento(ProductDTO(product_id="1", sku="S", name="X", categories=["7"]))
    links = payload["extension_attributes"]["category_links"]
    assert [row["category_id"] for row in links] == ["7"]


def test_the_two_fields_do_not_fight():
    """Cind vin amindoua, cistiga `category_ids` — ala e cimpul de ID-uri."""
    payload = product_to_magento(
        ProductDTO(product_id="1", sku="S", name="X", categories=["nume"], category_ids=["42"])
    )
    links = payload["extension_attributes"]["category_links"]
    assert [row["category_id"] for row in links] == ["42"]
