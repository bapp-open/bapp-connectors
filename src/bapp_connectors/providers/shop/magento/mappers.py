"""
Magento 2 <-> DTO mappers.

Key Magento differences:
- Products identified by SKU (product_id in DTOs = Magento entity_id, but SKU is primary)
- Prices stored without tax by default (configurable)
- Categories are a tree, flattened to list with parent_id
- Orders use entity_id (int) and increment_id (display number)
- Custom attributes stored as [{attribute_code, value}] array
- Stock is separate from product (extension_attributes.stock_item or stockItems endpoint)
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    Address,
    AttributeDefinition,
    AttributeValue,
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    PaymentType,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductVariant,
    ProviderMeta,
    RelatedProductLink,
)

# ── Status mappings ──

MAGENTO_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "pending": OrderStatus.PENDING,
    "pending_payment": OrderStatus.PENDING,
    "holded": OrderStatus.PENDING,
    "processing": OrderStatus.PROCESSING,
    "complete": OrderStatus.DELIVERED,
    "closed": OrderStatus.REFUNDED,
    "canceled": OrderStatus.CANCELLED,
    "fraud": OrderStatus.CANCELLED,
    "payment_review": OrderStatus.PENDING,
}

ORDER_STATUS_TO_MAGENTO: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "pending",
    OrderStatus.ACCEPTED: "processing",
    OrderStatus.PROCESSING: "processing",
    OrderStatus.SHIPPED: "complete",
    OrderStatus.DELIVERED: "complete",
    OrderStatus.CANCELLED: "canceled",
    OrderStatus.REFUNDED: "closed",
    OrderStatus.RETURNED: "closed",
}

MAGENTO_PAYMENT_MAP: dict[str, PaymentType] = {
    "checkmo": PaymentType.PAYMENT_ORDER,
    "banktransfer": PaymentType.BANK_TRANSFER,
    "cashondelivery": PaymentType.CASH_ON_DELIVERY,
    "stripe_payments": PaymentType.ONLINE_CARD,
    "braintree": PaymentType.ONLINE_CARD,
    "paypal_express": PaymentType.ONLINE_CARD,
    "authorizenet_directpost": PaymentType.ONLINE_CARD,
}


# ── Helpers ──


def _get_custom_attr(product: dict, code: str) -> str | None:
    """Extract a custom attribute value from a Magento product."""
    for attr in product.get("custom_attributes", []):
        if attr.get("attribute_code") == code:
            val = attr.get("value")
            return str(val) if val is not None else None
    return None


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
    return None


# ── Product mappers ──


def product_from_magento(data: dict, price_from_provider=None) -> Product:
    """Map a Magento product to a normalized Product DTO."""
    convert = price_from_provider or (lambda x: x)

    price = None
    if data.get("price") is not None:
        with contextlib.suppress(Exception):
            price = convert(Decimal(str(data["price"])))

    # Extract stock from extension_attributes
    stock = None
    ext = data.get("extension_attributes", {})
    if ext and isinstance(ext, dict):
        stock_item = ext.get("stock_item", {})
        if stock_item and isinstance(stock_item, dict):
            qty = stock_item.get("qty")
            if qty is not None:
                stock = int(float(str(qty)))

    # Categories from extension_attributes.category_links
    categories = []
    if ext and isinstance(ext, dict):
        for link in ext.get("category_links", []):
            categories.append(str(link.get("category_id", "")))

    # Photos from media_gallery_entries
    photos = []
    for entry in data.get("media_gallery_entries", []):
        if entry.get("media_type") == "image" and not entry.get("disabled"):
            photos.append(ProductPhoto(
                url=entry.get("file", ""),
                position=entry.get("position", 0),
                alt_text=entry.get("label", ""),
            ))

    description = _get_custom_attr(data, "description") or ""

    return Product(
        product_id=str(data.get("id", "")),
        sku=data.get("sku", ""),
        barcode=_get_custom_attr(data, "ean") or _get_custom_attr(data, "barcode") or "",
        name=data.get("name", ""),
        description=description,
        price=price,
        currency="",
        stock=stock,
        active=data.get("status") == 1,
        categories=categories,
        photos=photos,
        provider_meta=ProviderMeta(
            provider="magento",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            "sku": data.get("sku", ""),
            "type_id": data.get("type_id", ""),
            "attribute_set_id": data.get("attribute_set_id"),
            "visibility": data.get("visibility"),
            "weight": data.get("weight"),
        },
    )


def products_from_magento(response: dict, page: int = 1, price_from_provider=None) -> PaginatedResult[Product]:
    """Map a Magento products search response to PaginatedResult[Product]."""
    items = response.get("items", [])
    total = response.get("total_count", 0)
    products = [product_from_magento(p, price_from_provider=price_from_provider) for p in items]

    page_size = 100
    has_more = (page * page_size) < total

    return PaginatedResult(
        items=products,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=total,
    )


def product_to_magento(product, price_to_provider=None) -> dict:
    """Map a Product DTO to a Magento product create/update payload."""
    convert = price_to_provider or (lambda x: x)
    data: dict = {
        "sku": product.sku or "",
        "name": product.name,
        "status": 1 if product.active else 2,
        "visibility": 4,
        "type_id": "simple",
        "attribute_set_id": 4,
    }
    if product.price is not None:
        data["price"] = float(convert(product.price))
    if product.description:
        data["custom_attributes"] = [{"attribute_code": "description", "value": product.description}]
    if product.categories:
        data.setdefault("extension_attributes", {})["category_links"] = [
            {"category_id": cat, "position": 0} for cat in product.categories
        ]
    return data


def product_update_to_magento(update, price_to_provider=None) -> dict:
    """Map a ProductUpdate DTO to a Magento product update payload."""
    convert = price_to_provider or (lambda x: x)
    data: dict = {}
    if update.name is not None:
        data["name"] = update.name
    if update.sku is not None:
        data["sku"] = update.sku
    if update.price is not None:
        data["price"] = float(convert(update.price))
    if update.active is not None:
        data["status"] = 1 if update.active else 2
    if update.description is not None:
        data.setdefault("custom_attributes", []).append({"attribute_code": "description", "value": update.description})
    if update.extra:
        data.update(update.extra)
    return data


# ── Order mappers ──


def _map_magento_address(addr: dict | None) -> tuple[Contact | None, Address | None]:
    if not addr:
        return None, None
    name = f"{addr.get('firstname', '')} {addr.get('lastname', '')}".strip()
    street_parts = addr.get("street", [])
    street = ", ".join(street_parts) if isinstance(street_parts, list) else str(street_parts)
    address = Address(
        street=street,
        city=addr.get("city", ""),
        region=addr.get("region", ""),
        postal_code=addr.get("postcode", ""),
        country=addr.get("country_id", ""),
    )
    contact = Contact(
        name=name,
        company_name=addr.get("company", "") or "",
        email=addr.get("email", ""),
        phone=addr.get("telephone", ""),
        address=address,
        extra={"vat_id": addr.get("vat_id", "")},
    )
    return contact, address


def order_from_magento(data: dict, price_from_provider=None, status_mapper=None) -> Order:
    """Map a Magento order to a normalized Order DTO."""
    convert = price_from_provider or (lambda x: x)

    items = []
    for item in data.get("items", []):
        if item.get("product_type") == "configurable":
            continue  # skip parent configurable items, keep simple children
        raw_price = Decimal(str(item.get("price_incl_tax", item.get("price", 0))))
        items.append(OrderItem(
            item_id=str(item.get("item_id", "")),
            product_id=str(item.get("product_id", "")),
            sku=item.get("sku", ""),
            name=item.get("name", ""),
            quantity=Decimal(str(item.get("qty_ordered", 1))),
            unit_price=convert(raw_price),
            currency=data.get("order_currency_code", ""),
            tax_rate=Decimal(str(item.get("tax_percent", 0))) if item.get("tax_percent") else None,
        ))

    raw_status = data.get("status", "")
    if status_mapper:
        status = status_mapper.to_framework(raw_status)
    else:
        status = MAGENTO_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    # Payment
    payment_data = data.get("payment", {})
    payment_method = payment_data.get("method", "") if isinstance(payment_data, dict) else ""
    payment_type = MAGENTO_PAYMENT_MAP.get(payment_method, PaymentType.OTHER)

    billing_contact, _ = _map_magento_address(data.get("billing_address"))

    # Shipping from extension_attributes
    shipping_contact = None
    shipping_addr = None
    ext = data.get("extension_attributes", {})
    if ext and isinstance(ext, dict):
        shipping_assignments = ext.get("shipping_assignments", [])
        if shipping_assignments:
            shipping_data = shipping_assignments[0].get("shipping", {}).get("address")
            shipping_contact, shipping_addr = _map_magento_address(shipping_data)

    total = convert(Decimal(str(data.get("grand_total", 0))))

    return Order(
        order_id=str(data.get("increment_id", data.get("entity_id", ""))),
        external_id=str(data.get("entity_id", "")),
        status=status,
        raw_status=raw_status,
        payment_status=PaymentStatus.PAID if status in (OrderStatus.PROCESSING, OrderStatus.DELIVERED) else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency=data.get("order_currency_code", ""),
        items=items,
        billing=billing_contact,
        shipping=shipping_contact,
        shipping_address=shipping_addr,
        total=total,
        created_at=_parse_datetime(data.get("created_at", "")),
        updated_at=_parse_datetime(data.get("updated_at", "")),
        provider_meta=ProviderMeta(
            provider="magento",
            raw_id=str(data.get("entity_id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


def orders_from_magento(response: dict, page: int = 1, price_from_provider=None, status_mapper=None) -> PaginatedResult[Order]:
    items = response.get("items", [])
    total = response.get("total_count", 0)
    orders = [order_from_magento(o, price_from_provider=price_from_provider, status_mapper=status_mapper) for o in items]
    page_size = 100
    has_more = (page * page_size) < total
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=total,
    )


# ── Category mappers ──


def _flatten_category_tree(node: dict, result: list[ProductCategory], depth: int = 0) -> None:
    """Recursively flatten Magento's category tree."""
    cat_id = str(node.get("id", ""))
    parent_id = str(node.get("parent_id", ""))
    if parent_id in ("0", "1"):
        parent_id = None  # root categories

    result.append(ProductCategory(
        category_id=cat_id,
        name=node.get("name", ""),
        parent_id=parent_id,
        extra={"level": node.get("level", 0), "is_active": node.get("is_active", True)},
    ))

    for child in node.get("children_data", []):
        _flatten_category_tree(child, result, depth + 1)


def categories_from_magento(tree: dict) -> list[ProductCategory]:
    """Flatten Magento's category tree into a list with parent_id."""
    result: list[ProductCategory] = []
    _flatten_category_tree(tree, result)
    return result


def categories_from_magento_list(response: dict) -> list[ProductCategory]:
    """Map Magento /categories/list flat response."""
    categories = []
    for item in response.get("items", []):
        parent_id = str(item.get("parent_id", ""))
        if parent_id in ("0", "1"):
            parent_id = None
        categories.append(ProductCategory(
            category_id=str(item.get("id", "")),
            name=item.get("name", ""),
            parent_id=parent_id,
            extra={"level": item.get("level", 0), "is_active": item.get("is_active", True)},
        ))
    return categories


def category_from_magento(data: dict) -> ProductCategory:
    parent_id = str(data.get("parent_id", ""))
    if parent_id in ("0", "1"):
        parent_id = None
    return ProductCategory(
        category_id=str(data.get("id", "")),
        name=data.get("name", ""),
        parent_id=parent_id,
    )


# ── Attribute mappers ──


def attribute_definition_from_magento(data: dict) -> AttributeDefinition:
    """Map a Magento product attribute to AttributeDefinition DTO."""
    values = []
    for opt in data.get("options", []):
        if opt.get("value"):
            values.append(AttributeValue(
                value_id=str(opt.get("value", "")),
                name=opt.get("label", ""),
            ))
    return AttributeDefinition(
        attribute_id=str(data.get("attribute_id", data.get("attribute_code", ""))),
        name=data.get("default_frontend_label", data.get("frontend_label", "")),
        slug=data.get("attribute_code", ""),
        attribute_type=data.get("frontend_input", "select"),
        values=values,
        extra={"attribute_code": data.get("attribute_code", "")},
    )


# ── Variant mappers (configurable product children) ──


def variant_from_magento(child: dict, price_from_provider=None) -> ProductVariant:
    """Map a Magento configurable child product to ProductVariant DTO."""
    convert = price_from_provider or (lambda x: x)
    attributes = {}
    for attr in child.get("custom_attributes", []):
        attributes[attr.get("attribute_code", "")] = str(attr.get("value", ""))

    price = None
    if child.get("price") is not None:
        with contextlib.suppress(Exception):
            price = convert(Decimal(str(child["price"])))

    stock = None
    ext = child.get("extension_attributes", {})
    if ext and isinstance(ext, dict):
        stock_item = ext.get("stock_item", {})
        if stock_item and isinstance(stock_item, dict):
            qty = stock_item.get("qty")
            if qty is not None:
                stock = int(float(str(qty)))

    return ProductVariant(
        variant_id=str(child.get("id", "")),
        sku=child.get("sku", ""),
        name=child.get("name", ""),
        price=price,
        stock=stock,
        attributes=attributes,
        active=child.get("status") == 1,
    )


# ── Related product mappers ──


def related_links_from_magento(links: list[dict], link_type: str) -> list[RelatedProductLink]:
    return [
        RelatedProductLink(
            product_id=link.get("linked_product_sku", ""),
            link_type=link_type,
            position=link.get("position", 0),
        )
        for link in links
    ]


def related_link_to_magento(sku: str, link: RelatedProductLink) -> dict:
    return {
        "sku": sku,
        "link_type": link.link_type,
        "linked_product_sku": link.product_id,
        "linked_product_type": "simple",
        "position": link.position,
    }
