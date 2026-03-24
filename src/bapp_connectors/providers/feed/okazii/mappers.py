"""
Okazii.ro feed mappers.

Converts Product DTOs to Okazii AUCTION XML items.
Okazii uses a custom XML schema with <OKAZII> root and <AUCTION> children.
Variants are represented as <STOCKS> entries (Size/Color).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from bapp_connectors.providers.feed._utils import (
    extract_brand,
    format_price_plain,
    strip_html,
)
from bapp_connectors.providers.feed.okazii.models import (
    OkaziiCourier,
    OkaziiFeedItem,
    OkaziiStock,
)

if TYPE_CHECKING:
    from bapp_connectors.core.dto.product import Product

# Common attribute names for Size and Color (Romanian + English)
_SIZE_ATTRS = frozenset({"size", "marime", "mărime", "dimensiune"})
_COLOR_ATTRS = frozenset({"color", "colour", "culoare"})


def product_to_feed_item(product: Product, config: dict) -> OkaziiFeedItem:
    """Map a Product DTO to an OkaziiFeedItem."""
    currency = config.get("currency", "RON")
    brand = extract_brand(product, config.get("brand_fallback", ""))

    # Categories as " > " delimited
    category = " > ".join(product.categories) if product.categories else ""

    # Photos
    photos = [p.url for p in product.photos]

    # Description — strip HTML
    description = strip_html(product.description)

    # Discount price from extra
    discount_price = ""
    sale_price = product.extra.get("sale_price") or product.extra.get("discount_price")
    if sale_price is not None:
        discount_price = format_price_plain(sale_price)

    # Attributes (non-variant): all attributes that are not used for variants
    attributes = {}
    for attr in product.attributes:
        if not attr.used_for_variants and attr.values:
            attributes[attr.attribute_name] = attr.values[0]

    # Stock variants
    include_variants = str(config.get("include_variants", "true")).lower() in ("true", "1", "yes")
    stocks: list[OkaziiStock] = []
    total_amount = product.stock or 0

    if include_variants and product.variants:
        total_amount = 0
        for variant in product.variants:
            if not variant.active:
                continue
            stock_amount = variant.stock or 0
            total_amount += stock_amount

            # Extract size and color from variant attributes
            size = ""
            color = ""
            for attr_name, attr_val in variant.attributes.items():
                if attr_name.lower().strip() in _SIZE_ATTRS:
                    size = str(attr_val)
                elif attr_name.lower().strip() in _COLOR_ATTRS:
                    color = str(attr_val)

            stocks.append(OkaziiStock(
                amount=stock_amount,
                size=size,
                color=color,
                gtin=variant.barcode or "",
            ))

    # Determine in_stock
    in_stock = 1 if total_amount > 0 and product.active else 0

    # Payment settings
    payment_personal = _bool_to_int(config.get("payment_personal", "false"))
    payment_ramburs = _bool_to_int(config.get("payment_ramburs", "true"))
    payment_avans = _bool_to_int(config.get("payment_avans", "true"))

    # Delivery
    delivery_time = int(config.get("delivery_time", 3))
    couriers: list[OkaziiCourier] = []
    courier_name = config.get("courier_name", "")
    courier_price = config.get("courier_price", "")
    if courier_name:
        couriers.append(OkaziiCourier(
            name=courier_name,
            area="in romania",
            price=courier_price,
            currency=currency,
        ))

    # Return policy
    return_accept = _bool_to_int(config.get("return_accept", "true"))
    return_days = int(config.get("return_days", 14))

    return OkaziiFeedItem(
        unique_id=str(product.product_id),
        title=product.name,
        category=category,
        description=description,
        price=format_price_plain(product.price),
        discount_price=discount_price,
        currency=currency,
        amount=total_amount,
        brand=brand,
        sku=product.sku or "",
        gtin=product.barcode or "",
        in_stock=in_stock,
        state=int(config.get("default_condition", 1)),
        invoice=int(config.get("invoice", 1)),
        warranty=int(config.get("warranty", 1)),
        photos=photos,
        payment_personal=payment_personal,
        payment_ramburs=payment_ramburs,
        payment_avans=payment_avans,
        delivery_personal=0,
        delivery_time=delivery_time,
        couriers=couriers,
        return_accept=return_accept,
        return_days=return_days,
        return_method=2,  # seller pays return shipping
        return_cost=0,  # free returns
        attributes=attributes,
        stocks=stocks,
    )


def validate_feed_item(item: OkaziiFeedItem) -> list[tuple[str, str, bool]]:
    """Validate an OkaziiFeedItem. Returns list of (field, message, required)."""
    errors = []
    if not item.unique_id:
        errors.append(("unique_id", "UNIQUEID is required", True))
    if not item.title:
        errors.append(("title", "TITLE is required", True))
    if not item.price:
        errors.append(("price", "PRICE is required", True))
    if not item.category:
        errors.append(("category", "CATEGORY is required", True))
    if not item.photos:
        errors.append(("photos", "At least one photo URL is required", True))
    if not item.description:
        errors.append(("description", "DESCRIPTION is recommended", False))
    if not item.brand:
        errors.append(("brand", "BRAND is recommended", False))
    return errors


def feed_items_to_xml(items: list[OkaziiFeedItem]) -> str:
    """Serialize OkaziiFeedItems to Okazii XML format.

    Output structure:
    <OKAZII>
      <AUCTION>...</AUCTION>
      ...
    </OKAZII>
    """
    root = ET.Element("OKAZII")

    for item in items:
        auction = ET.SubElement(root, "AUCTION")

        # Core fields
        ET.SubElement(auction, "UNIQUEID").text = item.unique_id
        ET.SubElement(auction, "TITLE").text = item.title
        ET.SubElement(auction, "CATEGORY").text = item.category

        # Description with CDATA — ElementTree doesn't support CDATA natively,
        # so we'll post-process the output
        desc_el = ET.SubElement(auction, "DESCRIPTION")
        desc_el.text = item.description
        desc_el.set("_cdata", "true")

        ET.SubElement(auction, "PRICE").text = item.price
        if item.discount_price:
            ET.SubElement(auction, "DISCOUNT_PRICE").text = item.discount_price
        ET.SubElement(auction, "CURRENCY").text = item.currency
        ET.SubElement(auction, "AMOUNT").text = str(item.amount)

        if item.brand:
            ET.SubElement(auction, "BRAND").text = item.brand
        if item.sku:
            ET.SubElement(auction, "SKU").text = item.sku
        if item.gtin:
            ET.SubElement(auction, "GTIN").text = item.gtin

        ET.SubElement(auction, "IN_STOCK").text = str(item.in_stock)
        ET.SubElement(auction, "STATE").text = str(item.state)
        ET.SubElement(auction, "INVOICE").text = str(item.invoice)
        ET.SubElement(auction, "WARRANTY").text = str(item.warranty)

        # Photos
        if item.photos:
            photos_el = ET.SubElement(auction, "PHOTOS")
            for url in item.photos:
                ET.SubElement(photos_el, "URL").text = url

        # Payment
        payment_el = ET.SubElement(auction, "PAYMENT")
        ET.SubElement(payment_el, "PERSONAL").text = str(item.payment_personal)
        ET.SubElement(payment_el, "RAMBURS").text = str(item.payment_ramburs)
        ET.SubElement(payment_el, "AVANS").text = str(item.payment_avans)

        # Delivery
        delivery_el = ET.SubElement(auction, "DELIVERY")
        ET.SubElement(delivery_el, "PERSONAL").text = str(item.delivery_personal)
        ET.SubElement(delivery_el, "DELIVERY_TIME").text = str(item.delivery_time)
        for courier in item.couriers:
            courier_el = ET.SubElement(delivery_el, "COURIERS")
            ET.SubElement(courier_el, "NAME").text = courier.name
            ET.SubElement(courier_el, "AREA").text = courier.area
            ET.SubElement(courier_el, "PRICE").text = courier.price
            ET.SubElement(courier_el, "CURRENCY").text = courier.currency

        # Return
        return_el = ET.SubElement(auction, "RETURN")
        ET.SubElement(return_el, "ACCEPT").text = str(item.return_accept)
        ET.SubElement(return_el, "DAYS").text = str(item.return_days)
        ET.SubElement(return_el, "METHOD").text = str(item.return_method)
        ET.SubElement(return_el, "COST").text = str(item.return_cost)

        # Attributes
        if item.attributes:
            attrs_el = ET.SubElement(auction, "ATTRIBUTES")
            for attr_name, attr_val in item.attributes.items():
                attr_el = ET.SubElement(attrs_el, "ATTRIBUTE")
                attr_el.set("NAME", attr_name)
                attr_el.text = attr_val

        # Stocks (variants)
        if item.stocks:
            stocks_el = ET.SubElement(auction, "STOCKS")
            for stock in item.stocks:
                stock_el = ET.SubElement(stocks_el, "STOCK")
                ET.SubElement(stock_el, "AMOUNT").text = str(stock.amount)
                if stock.size:
                    ET.SubElement(stock_el, "MARIME").text = stock.size
                if stock.color:
                    ET.SubElement(stock_el, "CULOARE").text = stock.color
                if stock.gtin:
                    ET.SubElement(stock_el, "GTIN").text = stock.gtin

    ET.indent(root, space="  ")
    xml_str = ET.tostring(root, encoding="unicode")

    # Post-process: wrap DESCRIPTION content in CDATA
    xml_str = _wrap_cdata(xml_str)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


def _wrap_cdata(xml_str: str) -> str:
    """Wrap DESCRIPTION element content in CDATA sections.

    ElementTree doesn't support CDATA natively, so we post-process.
    Also removes the internal _cdata attribute marker.
    """
    import re

    # Remove the _cdata="true" marker attribute
    xml_str = xml_str.replace(' _cdata="true"', "")

    # Wrap DESCRIPTION content in CDATA
    def _cdata_replace(match: re.Match) -> str:
        content = match.group(1)
        if content:
            return f"<DESCRIPTION><![CDATA[{content}]]></DESCRIPTION>"
        return "<DESCRIPTION></DESCRIPTION>"

    return re.sub(r"<DESCRIPTION>(.*?)</DESCRIPTION>", _cdata_replace, xml_str, flags=re.DOTALL)


def _bool_to_int(value: str | bool) -> int:
    """Convert a bool-like setting value to 0 or 1."""
    if isinstance(value, bool):
        return 1 if value else 0
    return 1 if str(value).lower() in ("true", "1", "yes") else 0
