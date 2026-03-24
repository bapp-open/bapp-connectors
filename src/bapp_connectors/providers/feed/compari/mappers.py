"""
Compari.ro feed mappers.

Converts Product DTOs to Compari.ro feed items and serializes to XML or CSV.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from bapp_connectors.providers.feed._utils import (
    build_product_url,
    extract_brand,
    format_price_plain,
    strip_html,
    truncate,
)
from bapp_connectors.providers.feed.compari.models import CompariFeedItem

if TYPE_CHECKING:
    from bapp_connectors.core.dto.product import Product

CSV_COLUMNS = [
    "identifier", "name", "product_url", "price", "category",
    "image_url", "description", "manufacturer", "currency",
    "ean_code", "delivery_time", "delivery_cost",
]


def product_to_feed_item(product: Product, item: dict, config: dict) -> CompariFeedItem:
    """Map a Product DTO to a CompariFeedItem."""
    base_url = config.get("base_url", "")
    url_template = config.get("product_url_template", "{base_url}/product/{product_id}")
    link = build_product_url(url_template, product, base_url)

    if item.get("variant"):
        link = f"{link}?variant={item['variant'].variant_id}"

    currency = config.get("currency", "RON")
    description = truncate(strip_html(product.description), 5000)
    manufacturer = extract_brand(product, config.get("manufacturer_fallback", ""))

    # Categories as semicolon-delimited path
    category = " > ".join(product.categories) if product.categories else ""

    return CompariFeedItem(
        identifier=item["item_id"],
        name=truncate(item["name"], 200),
        product_url=link,
        price=format_price_plain(item["price"]),
        category=category,
        image_url=item["image_url"],
        description=description,
        manufacturer=manufacturer,
        currency=currency,
        ean_code=item["barcode"] or "",
        delivery_time=config.get("default_delivery_time", ""),
        delivery_cost=config.get("default_delivery_cost", ""),
    )


def validate_feed_item(item: CompariFeedItem) -> list[tuple[str, str, bool]]:
    """Validate a CompariFeedItem. Returns list of (field, message, required)."""
    errors = []
    if not item.identifier:
        errors.append(("identifier", "Product identifier is required", True))
    if not item.name:
        errors.append(("name", "Product name is required", True))
    if not item.product_url:
        errors.append(("product_url", "Product URL is required", True))
    if not item.price:
        errors.append(("price", "Price is required", True))
    if not item.category:
        errors.append(("category", "Category is required", True))
    if not item.image_url:
        errors.append(("image_url", "Image URL is required", True))
    if not item.description:
        errors.append(("description", "Description is recommended", False))
    if not item.manufacturer:
        errors.append(("manufacturer", "Manufacturer is recommended", False))
    return errors


def feed_items_to_xml(items: list[CompariFeedItem]) -> str:
    """Serialize CompariFeedItems to Compari.ro XML format."""
    root = ET.Element("products")

    for feed_item in items:
        product_el = ET.SubElement(root, "product")
        ET.SubElement(product_el, "identifier").text = feed_item.identifier
        ET.SubElement(product_el, "name").text = feed_item.name
        ET.SubElement(product_el, "product_url").text = feed_item.product_url
        ET.SubElement(product_el, "price").text = feed_item.price
        ET.SubElement(product_el, "category").text = feed_item.category
        ET.SubElement(product_el, "image_url").text = feed_item.image_url
        ET.SubElement(product_el, "description").text = feed_item.description
        ET.SubElement(product_el, "currency").text = feed_item.currency
        if feed_item.manufacturer:
            ET.SubElement(product_el, "manufacturer").text = feed_item.manufacturer
        if feed_item.ean_code:
            ET.SubElement(product_el, "ean_code").text = feed_item.ean_code
        if feed_item.delivery_time:
            ET.SubElement(product_el, "delivery_time").text = feed_item.delivery_time
        if feed_item.delivery_cost:
            ET.SubElement(product_el, "delivery_cost").text = feed_item.delivery_cost

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def feed_items_to_csv(items: list[CompariFeedItem]) -> str:
    """Serialize CompariFeedItems to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(CSV_COLUMNS)

    for item in items:
        writer.writerow([
            item.identifier,
            item.name,
            item.product_url,
            item.price,
            item.category,
            item.image_url,
            item.description,
            item.manufacturer,
            item.currency,
            item.ean_code,
            item.delivery_time,
            item.delivery_cost,
        ])

    return output.getvalue()
