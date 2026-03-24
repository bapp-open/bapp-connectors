"""
Google Merchant feed mappers.

Converts Product DTOs to Google Merchant feed items and serializes
to XML (RSS 2.0 with g: namespace) or CSV.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from bapp_connectors.providers.feed._utils import (
    build_product_url,
    extract_brand,
    format_price,
    resolve_availability,
    strip_html,
    truncate,
)
from bapp_connectors.providers.feed.google_merchant.models import GoogleFeedItem

if TYPE_CHECKING:
    from bapp_connectors.core.dto.product import Product

GOOGLE_NS = "http://base.google.com/ns/1.0"

# CSV column order
CSV_COLUMNS = [
    "id", "title", "description", "link", "image_link", "additional_image_link",
    "price", "availability", "condition", "brand", "gtin", "mpn", "product_type",
]


def product_to_feed_item(product: Product, item: dict, config: dict) -> GoogleFeedItem:
    """Map a Product DTO (or variant expansion) to a GoogleFeedItem.

    Args:
        product: The original Product DTO.
        item: An expanded item dict from expand_variants().
        config: Adapter settings (base_url, default_condition, etc.).
    """
    base_url = config.get("base_url", "")
    url_template = config.get("product_url_template", "{base_url}/product/{product_id}")
    link = build_product_url(url_template, product, base_url)

    # For variants, append variant ID to link
    if item.get("variant"):
        link = f"{link}?variant={item['variant'].variant_id}"

    currency = config.get("currency", "RON")
    description = truncate(strip_html(product.description), 5000)

    # Additional images (up to 10)
    additional_images = [p.url for p in product.photos[1:11]] if len(product.photos) > 1 else []

    # Brand extraction
    brand = extract_brand(product, config.get("brand_fallback", ""))

    # Categories as product_type (> delimited for Google)
    product_type = " > ".join(product.categories) if product.categories else ""

    return GoogleFeedItem(
        id=item["item_id"],
        title=truncate(item["name"], 150),
        description=description,
        link=link,
        image_link=item["image_url"],
        price=format_price(item["price"], currency),
        availability=resolve_availability(product, config.get("default_availability", "in stock")),
        condition=config.get("default_condition", "new"),
        brand=brand,
        gtin=item["barcode"] or "",
        mpn=item["sku"] or "",
        product_type=product_type,
        additional_image_links=additional_images,
    )


def validate_feed_item(item: GoogleFeedItem) -> list[tuple[str, str, bool]]:
    """Validate a GoogleFeedItem. Returns list of (field, message, required)."""
    errors = []
    if not item.id:
        errors.append(("id", "Product ID is required", True))
    if not item.title:
        errors.append(("title", "Title is required", True))
    if not item.link:
        errors.append(("link", "Product URL is required", True))
    if not item.image_link:
        errors.append(("image_link", "Image URL is required", True))
    if not item.price:
        errors.append(("price", "Price is required", True))
    if not item.description:
        errors.append(("description", "Description is recommended", False))
    if not item.brand and not item.gtin and not item.mpn:
        errors.append(("brand", "Brand, GTIN, or MPN is recommended", False))
    return errors


def feed_items_to_xml(items: list[GoogleFeedItem], config: dict) -> str:
    """Serialize a list of GoogleFeedItems to Google Merchant RSS 2.0 XML."""
    rss = ET.Element("rss", attrib={
        "version": "2.0",
        "xmlns:g": GOOGLE_NS,
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = config.get("feed_title", "Product Feed")
    ET.SubElement(channel, "description").text = config.get("feed_description", "")
    ET.SubElement(channel, "link").text = config.get("base_url", "")

    for feed_item in items:
        item_el = ET.SubElement(channel, "item")
        _add_g(item_el, "id", feed_item.id)
        _add_g(item_el, "title", feed_item.title)
        _add_g(item_el, "description", feed_item.description)
        _add_g(item_el, "link", feed_item.link)
        _add_g(item_el, "image_link", feed_item.image_link)
        for img in feed_item.additional_image_links:
            _add_g(item_el, "additional_image_link", img)
        _add_g(item_el, "price", feed_item.price)
        _add_g(item_el, "availability", feed_item.availability)
        _add_g(item_el, "condition", feed_item.condition)
        if feed_item.brand:
            _add_g(item_el, "brand", feed_item.brand)
        if feed_item.gtin:
            _add_g(item_el, "gtin", feed_item.gtin)
        if feed_item.mpn:
            _add_g(item_el, "mpn", feed_item.mpn)
        if feed_item.product_type:
            _add_g(item_el, "product_type", feed_item.product_type)

    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


def feed_items_to_csv(items: list[GoogleFeedItem]) -> str:
    """Serialize a list of GoogleFeedItems to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(CSV_COLUMNS)

    for item in items:
        writer.writerow([
            item.id,
            item.title,
            item.description,
            item.link,
            item.image_link,
            ",".join(item.additional_image_links),
            item.price,
            item.availability,
            item.condition,
            item.brand,
            item.gtin,
            item.mpn,
            item.product_type,
        ])

    return output.getvalue()


def _add_g(parent: ET.Element, tag: str, text: str) -> None:
    """Add a g:-namespaced subelement."""
    el = ET.SubElement(parent, f"{{{GOOGLE_NS}}}{tag}")
    el.text = text
