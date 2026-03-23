"""
WooCommerce <-> DTO mappers.

Converts between raw WooCommerce API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
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
    ProductAttribute,
    ProductCategory,
    ProductPhoto,
    ProductVariant,
    ProviderMeta,
    RelatedProductLink,
    WebhookEvent,
    WebhookEventType,
)

# ── Status mappings ──

WOO_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "pending": OrderStatus.PENDING,
    "processing": OrderStatus.PENDING,
    "on-hold": OrderStatus.PENDING,
    "completed": OrderStatus.DELIVERED,
    "cancelled": OrderStatus.CANCELLED,
    "refunded": OrderStatus.CANCELLED,
    "failed": OrderStatus.CANCELLED,
}

# Reverse mapping: framework OrderStatus → WooCommerce status string
ORDER_STATUS_TO_WOO: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "pending",
    OrderStatus.ACCEPTED: "processing",
    OrderStatus.PROCESSING: "processing",
    OrderStatus.SHIPPED: "completed",
    OrderStatus.DELIVERED: "completed",
    OrderStatus.CANCELLED: "cancelled",
    OrderStatus.RETURNED: "refunded",
    OrderStatus.REFUNDED: "refunded",
}

WOO_PAYMENT_METHOD_MAP: dict[str, PaymentType] = {
    "stripe": PaymentType.ONLINE_CARD,
    "stripe_cc": PaymentType.ONLINE_CARD,
    "revolut": PaymentType.ONLINE_CARD,
    "revolut_cc": PaymentType.ONLINE_CARD,
    "revolut_pay": PaymentType.ONLINE_CARD,
    "cod": PaymentType.CASH_ON_DELIVERY,
    "bacs": PaymentType.BANK_TRANSFER,
    "cheque": PaymentType.BANK_TRANSFER,
}

WOO_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "order.created": WebhookEventType.ORDER_CREATED,
    "order.updated": WebhookEventType.ORDER_UPDATED,
    "order.deleted": WebhookEventType.ORDER_CANCELLED,
    "product.created": WebhookEventType.PRODUCT_CREATED,
    "product.updated": WebhookEventType.PRODUCT_UPDATED,
    "product.deleted": WebhookEventType.PRODUCT_DELETED,
}


# ── Address / Contact mappers ──


def _map_address(addr: dict | None) -> Address | None:
    if not addr:
        return None
    street_parts = [addr.get("address_1", ""), addr.get("address_2", "")]
    street = ", ".join(p.strip() for p in street_parts if p.strip())
    return Address(
        street=street,
        city=addr.get("city", "").strip(),
        region=addr.get("state", "").strip(),
        postal_code=addr.get("postcode", "").strip(),
        country=addr.get("country", "").upper().strip(),
    )


def _map_contact(addr: dict | None) -> Contact | None:
    if not addr:
        return None
    first = addr.get("first_name", "").strip()
    last = addr.get("last_name", "").strip()
    return Contact(
        name=f"{first} {last}".strip(),
        company_name=addr.get("company", "").strip() if addr.get("company") else "",
        email=addr.get("email", "").lower().strip() if addr.get("email") else "",
        phone=addr.get("phone", "").strip() if addr.get("phone") else "",
        address=_map_address(addr),
    )


def _format_delivery_address(addr: dict | None) -> str:
    if not addr:
        return ""
    parts = []
    for key in ("address_1", "address_2", "city", "state", "postcode", "country"):
        if val := addr.get(key, ""):
            parts.append(val.strip())
    return ", ".join(parts)


# ── Order mappers ──


def _identity(price: Decimal) -> Decimal:
    return price


def order_from_woocommerce(data: dict, price_from_provider=None, status_mapper=None) -> Order:
    """Map a WooCommerce order response to a normalized Order DTO.

    Args:
        data: Raw WooCommerce order dict.
        price_from_provider: Optional callable to convert provider prices to net.
        status_mapper: Optional StatusMapper for tenant-configurable status mapping.
    """
    convert = price_from_provider or _identity
    items = []
    for line in data.get("line_items", []):
        raw_price = Decimal(str(line.get("price", 0)))
        items.append(
            OrderItem(
                item_id=str(line.get("id", "")),
                product_id=str(line.get("product_id", "")),
                sku=line.get("sku", ""),
                name=line.get("name", ""),
                quantity=Decimal(str(line.get("quantity", 1))),
                unit_price=convert(raw_price),
                currency=data.get("currency", "RON"),
                extra={
                    k: v for k, v in line.items() if k not in ("id", "product_id", "sku", "name", "quantity", "price")
                },
            )
        )

    order_date = None
    if ds := data.get("date_created"):
        with contextlib.suppress(ValueError, AttributeError):
            order_date = datetime.fromisoformat(ds.replace("Z", "+00:00"))

    raw_status = data.get("status", "")
    if status_mapper:
        status = status_mapper.to_framework(raw_status)
    else:
        status = WOO_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    payment_method = data.get("payment_method", "")
    payment_type = WOO_PAYMENT_METHOD_MAP.get(payment_method, PaymentType.OTHER)

    total = convert(Decimal(str(data.get("total", 0))))

    return Order(
        order_id=str(data.get("number", data.get("id", ""))),
        external_id=str(data.get("id", "")) if data.get("id") else None,
        status=status,
        raw_status=raw_status,
        payment_status=PaymentStatus.PAID if status == OrderStatus.DELIVERED else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency=data.get("currency", "RON"),
        items=items,
        billing=_map_contact(data.get("billing")),
        shipping=_map_contact(data.get("shipping")),
        shipping_address=_map_address(data.get("shipping")),
        delivery_address=_format_delivery_address(data.get("shipping")),
        total=total,
        created_at=order_date,
        provider_meta=ProviderMeta(
            provider="woocommerce",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "id",
                "number",
                "status",
                "currency",
                "date_created",
                "total",
                "payment_method",
                "billing",
                "shipping",
                "line_items",
            )
        },
    )


def orders_from_woocommerce(response: list[dict], page: int = 1, price_from_provider=None, status_mapper=None) -> PaginatedResult[Order]:
    """Map a WooCommerce orders list response to PaginatedResult[Order]."""
    orders = [order_from_woocommerce(o, price_from_provider=price_from_provider, status_mapper=status_mapper) for o in response]
    has_more = len(response) > 0 and len(response) >= 100
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


# ── Product mappers ──


def product_from_woocommerce(data: dict, price_from_provider=None) -> Product:
    """Map a WooCommerce product response to a normalized Product DTO.

    Args:
        data: Raw WooCommerce product dict.
        price_from_provider: Optional callable to convert provider prices to net.
    """
    convert = price_from_provider or _identity
    photos = []
    for img in data.get("images", []):
        photos.append(
            ProductPhoto(
                url=img.get("src", ""),
                position=img.get("position", 0),
                alt_text=img.get("alt", ""),
            )
        )

    price = None
    if raw_price := data.get("price"):
        with contextlib.suppress(Exception):
            price = convert(Decimal(str(raw_price)))

    categories = [str(cat.get("name", "")) for cat in data.get("categories", [])]

    # Parse product-level attributes
    attributes = product_attributes_from_woocommerce(data.get("attributes", []))

    # Parse related product links
    related = related_products_from_woocommerce(data)

    return Product(
        product_id=str(data.get("id", "")),
        sku=data.get("sku", ""),
        name=data.get("name", ""),
        description=data.get("description", ""),
        price=price,
        currency="",
        stock=data.get("stock_quantity"),
        active=data.get("status", "") == "publish",
        categories=categories,
        photos=photos,
        attributes=attributes,
        related=related,
        provider_meta=ProviderMeta(
            provider="woocommerce",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "id",
                "sku",
                "name",
                "description",
                "price",
                "stock_quantity",
                "status",
                "categories",
                "images",
            )
        },
    )


def products_from_woocommerce(response: list[dict], page: int = 1, price_from_provider=None) -> PaginatedResult[Product]:
    """Map a WooCommerce products list response to PaginatedResult[Product]."""
    products = [product_from_woocommerce(p, price_from_provider=price_from_provider) for p in response]
    has_more = len(response) > 0 and len(response) >= 100
    return PaginatedResult(
        items=products,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


# ── Outbound product mappers (local → WooCommerce) ──


def product_to_woocommerce(product, price_to_provider=None) -> dict:
    """Map a Product DTO to a WooCommerce create/update payload."""
    convert = price_to_provider or _identity
    data: dict = {
        "name": product.name,
        "status": "publish" if product.active else "draft",
    }
    if product.description:
        data["description"] = product.description
    if product.sku:
        data["sku"] = product.sku
    if product.price is not None:
        data["regular_price"] = str(convert(product.price))
    if product.stock is not None:
        data["stock_quantity"] = product.stock
        data["manage_stock"] = True
    if product.photos:
        data["images"] = [
            {"src": photo.url, "alt": photo.alt_text, "position": photo.position}
            for photo in product.photos
        ]
    if product.categories:
        data["categories"] = [{"name": cat} for cat in product.categories]
    if product.attributes:
        data["attributes"] = product_attributes_to_woocommerce(product.attributes)
        # If any attribute is used_for_variants, set product type to variable
        if any(a.used_for_variants for a in product.attributes):
            data["type"] = "variable"
    return data


def product_update_to_woocommerce(update, price_to_provider=None) -> dict:
    """Map a ProductUpdate DTO to a WooCommerce update payload."""
    convert = price_to_provider or _identity
    data: dict = {}
    if update.name is not None:
        data["name"] = update.name
    if update.description is not None:
        data["description"] = update.description
    if update.sku is not None:
        data["sku"] = update.sku
    if update.price is not None:
        data["regular_price"] = str(convert(update.price))
    if update.stock is not None:
        data["stock_quantity"] = update.stock
        data["manage_stock"] = True
    if update.active is not None:
        data["status"] = "publish" if update.active else "draft"
    if update.photos is not None:
        data["images"] = [
            {"src": p.url, "alt": p.alt_text, "position": p.position}
            for p in update.photos
        ]
    if update.categories is not None:
        data["categories"] = [{"name": cat} for cat in update.categories]
    if update.attributes is not None:
        data["attributes"] = product_attributes_to_woocommerce(update.attributes)
    if update.extra:
        data.update(update.extra)
    return data


# ── Category mappers ──


def category_from_woocommerce(data: dict) -> ProductCategory:
    """Map a WooCommerce category to a ProductCategory DTO."""
    return ProductCategory(
        category_id=str(data.get("id", "")),
        name=data.get("name", ""),
        parent_id=str(data["parent"]) if data.get("parent") else None,
        extra={k: v for k, v in data.items() if k not in ("id", "name", "parent")},
    )


def categories_from_woocommerce(response: list[dict]) -> list[ProductCategory]:
    """Map a WooCommerce categories list response."""
    return [category_from_woocommerce(c) for c in response]


# ── Attribute Definition mappers ──


def attribute_definition_from_woocommerce(data: dict, terms: list[dict] | None = None) -> AttributeDefinition:
    """Map WooCommerce global attribute + terms to AttributeDefinition DTO."""
    values = [
        AttributeValue(value_id=str(t.get("id", "")), name=t.get("name", ""), slug=t.get("slug", ""))
        for t in (terms or [])
    ]
    return AttributeDefinition(
        attribute_id=str(data.get("id", "")),
        name=data.get("name", ""),
        slug=data.get("slug", ""),
        attribute_type=data.get("type", "select"),
        values=values,
        provider_meta=ProviderMeta(provider="woocommerce", raw_id=str(data.get("id", "")), raw_payload=data, fetched_at=datetime.now(UTC)),
    )


def attribute_definition_to_woocommerce(attr: AttributeDefinition) -> dict:
    """Map AttributeDefinition DTO to WooCommerce create/update payload."""
    data: dict = {"name": attr.name, "type": attr.attribute_type or "select"}
    if attr.slug:
        data["slug"] = attr.slug
    return data


# ── Product-level Attribute mappers ──


def product_attributes_from_woocommerce(attrs: list[dict]) -> list[ProductAttribute]:
    """Map WooCommerce product.attributes[] to ProductAttribute DTOs."""
    return [
        ProductAttribute(
            attribute_id=str(a.get("id", "")),
            attribute_name=a.get("name", ""),
            values=a.get("options", []),
            visible=a.get("visible", True),
            used_for_variants=a.get("variation", False),
            position=a.get("position", 0),
        )
        for a in attrs
    ]


def product_attributes_to_woocommerce(attrs: list[ProductAttribute]) -> list[dict]:
    """Map ProductAttribute DTOs to WooCommerce product attributes payload."""
    result = []
    for attr in attrs:
        item: dict = {
            "name": attr.attribute_name,
            "visible": attr.visible,
            "variation": attr.used_for_variants,
            "options": attr.values,
            "position": attr.position,
        }
        if attr.attribute_id:
            item["id"] = int(attr.attribute_id)
        result.append(item)
    return result


# ── Variant mappers ──


def variant_from_woocommerce(data: dict, price_from_provider=None) -> ProductVariant:
    """Map a WooCommerce variation to ProductVariant DTO."""
    convert = price_from_provider or _identity
    price = None
    if raw_price := data.get("price"):
        with contextlib.suppress(Exception):
            price = convert(Decimal(str(raw_price)))
    attributes = {}
    for attr in data.get("attributes", []):
        key = attr.get("name", attr.get("slug", ""))
        attributes[key] = attr.get("option", "")
    image_url = ""
    if img := data.get("image"):
        image_url = img.get("src", "") if isinstance(img, dict) else ""
    weight = None
    if data.get("weight"):
        with contextlib.suppress(Exception):
            weight = Decimal(str(data["weight"]))
    return ProductVariant(
        variant_id=str(data.get("id", "")),
        sku=data.get("sku", ""),
        price=price,
        stock=data.get("stock_quantity"),
        attributes=attributes,
        image_url=image_url,
        weight=weight,
        active=data.get("status", "") == "publish",
        provider_meta=ProviderMeta(provider="woocommerce", raw_id=str(data.get("id", "")), raw_payload=data, fetched_at=datetime.now(UTC)),
    )


def variant_to_woocommerce(variant: ProductVariant, price_to_provider=None) -> dict:
    """Map ProductVariant DTO to WooCommerce variation payload."""
    convert = price_to_provider or _identity
    data: dict = {}
    if variant.sku:
        data["sku"] = variant.sku
    if variant.price is not None:
        data["regular_price"] = str(convert(variant.price))
    if variant.stock is not None:
        data["stock_quantity"] = variant.stock
        data["manage_stock"] = True
    if variant.attributes:
        data["attributes"] = [{"name": k, "option": v} for k, v in variant.attributes.items()]
    if variant.image_url:
        data["image"] = {"src": variant.image_url}
    return data


# ── Related Product mappers ──


def related_products_from_woocommerce(data: dict) -> list[RelatedProductLink]:
    """Extract related/upsell/cross-sell IDs from a WooCommerce product response."""
    links = []
    for pid in data.get("related_ids", []):
        links.append(RelatedProductLink(product_id=str(pid), link_type="related"))
    for pid in data.get("upsell_ids", []):
        links.append(RelatedProductLink(product_id=str(pid), link_type="upsell"))
    for pid in data.get("cross_sell_ids", []):
        links.append(RelatedProductLink(product_id=str(pid), link_type="crosssell"))
    return links


# ── Webhook mappers ──


def webhook_event_from_woocommerce(headers: dict, payload: dict) -> WebhookEvent:
    """Map a WooCommerce webhook payload to a normalized WebhookEvent."""
    topic = headers.get("X-WC-Webhook-Topic", headers.get("x-wc-webhook-topic", ""))
    resource = headers.get("X-WC-Webhook-Resource", headers.get("x-wc-webhook-resource", ""))
    event_id = headers.get("X-WC-Webhook-ID", headers.get("x-wc-webhook-id", ""))
    delivery_id = headers.get("X-WC-Webhook-Delivery-ID", headers.get("x-wc-webhook-delivery-id", ""))

    event_type = WOO_WEBHOOK_EVENT_MAP.get(topic, WebhookEventType.UNKNOWN)

    return WebhookEvent(
        event_id=str(delivery_id or event_id),
        event_type=event_type,
        provider="woocommerce",
        provider_event_type=topic,
        payload=payload,
        idempotency_key=str(delivery_id) if delivery_id else "",
        received_at=datetime.now(UTC),
        extra={"resource": resource, "webhook_id": event_id},
    )
