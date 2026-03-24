"""
Facebook/Meta Commerce feed mappers.

Converts Product DTOs to Facebook feed items and serializes to CSV or XML.
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
from bapp_connectors.providers.feed.facebook.models import FacebookFeedItem

if TYPE_CHECKING:
    from bapp_connectors.core.dto.product import Product

# Attribute names used for apparel fields
_GENDER_ATTRS = frozenset({"gender", "gen", "sex"})
_AGE_GROUP_ATTRS = frozenset({"age_group", "age group", "varsta", "vârstă"})
_COLOR_ATTRS = frozenset({"color", "colour", "culoare"})
_SIZE_ATTRS = frozenset({"size", "marime", "mărime"})

CSV_COLUMNS = [
    "id", "title", "description", "availability", "condition",
    "price", "link", "image_link", "additional_image_link",
    "brand", "gtin", "mpn", "product_type",
]

CSV_COLUMNS_APPAREL = [*CSV_COLUMNS, "gender", "age_group", "color", "size"]


def _extract_attr(product: Product, attr_names: frozenset) -> str:
    """Extract first matching attribute value by name."""
    for attr in product.attributes:
        if attr.attribute_name.lower().strip() in attr_names:
            if attr.values:
                return attr.values[0]
    return ""


def product_to_feed_item(product: Product, item: dict, config: dict) -> FacebookFeedItem:
    """Map a Product DTO to a FacebookFeedItem."""
    base_url = config.get("base_url", "")
    url_template = config.get("product_url_template", "{base_url}/product/{product_id}")
    link = build_product_url(url_template, product, base_url)

    if item.get("variant"):
        link = f"{link}?variant={item['variant'].variant_id}"

    currency = config.get("currency", "RON")
    description = truncate(strip_html(product.description), 5000)
    brand = extract_brand(product, config.get("brand_fallback", ""))
    additional_images = ",".join(p.url for p in product.photos[1:11]) if len(product.photos) > 1 else ""
    product_type = " > ".join(product.categories) if product.categories else ""

    apparel_mode = str(config.get("apparel_mode", "false")).lower() in ("true", "1", "yes")

    item_kwargs = {
        "id": item["item_id"],
        "title": truncate(item["name"], 150),
        "description": description,
        "availability": resolve_availability(product, "in stock"),
        "condition": config.get("default_condition", "new"),
        "price": format_price(item["price"], currency),
        "link": link,
        "image_link": item["image_url"],
        "brand": brand,
        "gtin": item["barcode"] or "",
        "mpn": item["sku"] or "",
        "product_type": product_type,
        "additional_image_link": additional_images,
    }

    if apparel_mode:
        # Try variant attributes first, then product attributes
        variant = item.get("variant")
        variant_attrs = variant.attributes if variant else {}
        item_kwargs["gender"] = variant_attrs.get("gender", "") or _extract_attr(product, _GENDER_ATTRS)
        item_kwargs["age_group"] = variant_attrs.get("age_group", "") or _extract_attr(product, _AGE_GROUP_ATTRS)
        item_kwargs["color"] = variant_attrs.get("color", "") or variant_attrs.get("Color", "") or _extract_attr(product, _COLOR_ATTRS)
        item_kwargs["size"] = variant_attrs.get("size", "") or variant_attrs.get("Size", "") or _extract_attr(product, _SIZE_ATTRS)

    return FacebookFeedItem(**item_kwargs)


def validate_feed_item(item: FacebookFeedItem) -> list[tuple[str, str, bool]]:
    """Validate a FacebookFeedItem. Returns list of (field, message, required)."""
    errors = []
    if not item.id:
        errors.append(("id", "Product ID is required", True))
    if not item.title:
        errors.append(("title", "Title is required", True))
    if not item.description:
        errors.append(("description", "Description is required", True))
    if not item.link:
        errors.append(("link", "Product URL is required", True))
    if not item.image_link:
        errors.append(("image_link", "Image URL is required", True))
    if not item.price:
        errors.append(("price", "Price is required", True))
    if not item.brand:
        errors.append(("brand", "Brand is recommended", False))
    return errors


def feed_items_to_csv(items: list[FacebookFeedItem], apparel_mode: bool = False) -> str:
    """Serialize FacebookFeedItems to CSV."""
    output = io.StringIO()
    columns = CSV_COLUMNS_APPAREL if apparel_mode else CSV_COLUMNS
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(columns)

    for item in items:
        row = [
            item.id, item.title, item.description, item.availability,
            item.condition, item.price, item.link, item.image_link,
            item.additional_image_link, item.brand, item.gtin, item.mpn,
            item.product_type,
        ]
        if apparel_mode:
            row.extend([item.gender, item.age_group, item.color, item.size])
        writer.writerow(row)

    return output.getvalue()


def feed_items_to_xml(items: list[FacebookFeedItem], config: dict) -> str:
    """Serialize FacebookFeedItems to RSS 2.0 XML (Facebook-compatible)."""
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = config.get("feed_title", "Product Feed")
    ET.SubElement(channel, "link").text = config.get("base_url", "")

    for feed_item in items:
        item_el = ET.SubElement(channel, "item")
        ET.SubElement(item_el, "id").text = feed_item.id
        ET.SubElement(item_el, "title").text = feed_item.title
        ET.SubElement(item_el, "description").text = feed_item.description
        ET.SubElement(item_el, "availability").text = feed_item.availability
        ET.SubElement(item_el, "condition").text = feed_item.condition
        ET.SubElement(item_el, "price").text = feed_item.price
        ET.SubElement(item_el, "link").text = feed_item.link
        ET.SubElement(item_el, "image_link").text = feed_item.image_link
        if feed_item.additional_image_link:
            ET.SubElement(item_el, "additional_image_link").text = feed_item.additional_image_link
        if feed_item.brand:
            ET.SubElement(item_el, "brand").text = feed_item.brand
        if feed_item.gtin:
            ET.SubElement(item_el, "gtin").text = feed_item.gtin
        if feed_item.mpn:
            ET.SubElement(item_el, "mpn").text = feed_item.mpn
        if feed_item.product_type:
            ET.SubElement(item_el, "product_type").text = feed_item.product_type

    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")
