"""
Shopify <-> DTO mappers.

Key Shopify differences:
- Products always have at least one variant (even "simple" products)
- Prices are on variants, not on the product itself
- Product options (max 3): option1/2/3 on variants
- Images are separate from variants (linked via variant.image_id)
- Orders use financial_status + fulfillment_status (not a single status)
- Tags are a comma-separated string, not a list
- Collections (categories) are separate resources
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    Address,
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductVariant,
    ProviderMeta,
    WebhookEvent,
    WebhookEventType,
)

# ── Status mappings ──

SHOPIFY_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "unfulfilled": OrderStatus.PENDING,
    "partial": OrderStatus.PROCESSING,
    "fulfilled": OrderStatus.DELIVERED,
    "restocked": OrderStatus.RETURNED,
}

SHOPIFY_FINANCIAL_STATUS_MAP: dict[str, PaymentStatus] = {
    "pending": PaymentStatus.UNPAID,
    "authorized": PaymentStatus.UNPAID,
    "paid": PaymentStatus.PAID,
    "partially_paid": PaymentStatus.PARTIALLY_PAID,
    "partially_refunded": PaymentStatus.PAID,
    "refunded": PaymentStatus.REFUNDED,
    "voided": PaymentStatus.FAILED,
}

ORDER_STATUS_TO_SHOPIFY: dict[OrderStatus, str] = {
    OrderStatus.DELIVERED: "fulfilled",
    OrderStatus.CANCELLED: "cancelled",
}

SHOPIFY_WEBHOOK_MAP: dict[str, WebhookEventType] = {
    "orders/create": WebhookEventType.ORDER_CREATED,
    "orders/updated": WebhookEventType.ORDER_UPDATED,
    "orders/cancelled": WebhookEventType.ORDER_CANCELLED,
    "products/create": WebhookEventType.PRODUCT_CREATED,
    "products/update": WebhookEventType.PRODUCT_UPDATED,
    "products/delete": WebhookEventType.PRODUCT_DELETED,
}


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


# ── Product mappers ──


def product_from_shopify(data: dict, price_from_provider=None) -> Product:
    convert = price_from_provider or (lambda x: x)

    variants_raw = data.get("variants", [])
    photos = [
        ProductPhoto(url=img.get("src", ""), position=img.get("position", 0), alt_text=img.get("alt", ""))
        for img in data.get("images", [])
    ]

    # Price from the first variant
    price = None
    if variants_raw:
        with contextlib.suppress(Exception):
            price = convert(Decimal(str(variants_raw[0].get("price", 0))))

    # Stock from the first variant
    stock = variants_raw[0].get("inventory_quantity") if variants_raw else None

    # Map variants
    variants = [variant_from_shopify(v, price_from_provider=price_from_provider) for v in variants_raw]

    # Tags as categories
    tags = data.get("tags", "")
    categories = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    return Product(
        product_id=str(data.get("id", "")),
        sku=variants_raw[0].get("sku", "") if variants_raw else "",
        barcode=variants_raw[0].get("barcode", "") if variants_raw else "",
        name=data.get("title", ""),
        description=data.get("body_html", ""),
        price=price,
        stock=stock,
        active=data.get("status") == "active",
        categories=categories,
        photos=photos,
        variants=variants if len(variants) > 1 else [],
        provider_meta=ProviderMeta(
            provider="shopify",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            "vendor": data.get("vendor", ""),
            "product_type": data.get("product_type", ""),
            "handle": data.get("handle", ""),
        },
    )


def products_from_shopify(response: list[dict], price_from_provider=None) -> PaginatedResult[Product]:
    products = [product_from_shopify(p, price_from_provider=price_from_provider) for p in response]
    return PaginatedResult(
        items=products,
        has_more=len(response) >= 50,
        total=None,
    )


def product_to_shopify(product, price_to_provider=None) -> dict:
    convert = price_to_provider or (lambda x: x)
    data: dict = {
        "title": product.name,
        "body_html": product.description or "",
        "status": "active" if product.active else "draft",
    }
    if product.categories:
        data["tags"] = ", ".join(product.categories)

    # Create default variant with price/sku/stock
    variant: dict = {}
    if product.price is not None:
        variant["price"] = str(convert(product.price))
    if product.sku:
        variant["sku"] = product.sku
    if product.barcode:
        variant["barcode"] = product.barcode
    if variant:
        data["variants"] = [variant]

    if product.photos:
        data["images"] = [{"src": p.url, "alt": p.alt_text} for p in product.photos]

    return data


# ── Variant mappers ──


def variant_from_shopify(data: dict, price_from_provider=None) -> ProductVariant:
    convert = price_from_provider or (lambda x: x)
    price = None
    with contextlib.suppress(Exception):
        price = convert(Decimal(str(data.get("price", 0))))

    attributes = {}
    for i in range(1, 4):
        opt = data.get(f"option{i}")
        if opt and opt != "Default Title":
            attributes[f"option{i}"] = opt

    weight = None
    if data.get("weight"):
        with contextlib.suppress(Exception):
            weight = Decimal(str(data["weight"]))

    return ProductVariant(
        variant_id=str(data.get("id", "")),
        sku=data.get("sku", ""),
        barcode=data.get("barcode", ""),
        name=data.get("title", ""),
        price=price,
        stock=data.get("inventory_quantity"),
        attributes=attributes,
        weight=weight,
        active=True,
    )


def variant_to_shopify(variant: ProductVariant, price_to_provider=None) -> dict:
    convert = price_to_provider or (lambda x: x)
    data: dict = {}
    if variant.sku:
        data["sku"] = variant.sku
    if variant.barcode:
        data["barcode"] = variant.barcode
    if variant.price is not None:
        data["price"] = str(convert(variant.price))
    if variant.attributes:
        for i, (k, v) in enumerate(variant.attributes.items(), 1):
            if i <= 3:
                data[f"option{i}"] = v
    return data


# ── Order mappers ──


def _map_shopify_address(addr: dict | None) -> tuple[Contact | None, Address | None]:
    if not addr:
        return None, None
    name = f"{addr.get('first_name', '')} {addr.get('last_name', '')}".strip()
    address = Address(
        street=f"{addr.get('address1', '')} {addr.get('address2', '')}".strip(),
        city=addr.get("city", ""),
        region=addr.get("province", ""),
        postal_code=addr.get("zip", ""),
        country=addr.get("country_code", ""),
    )
    contact = Contact(
        name=name or addr.get("name", ""),
        company_name=addr.get("company", ""),
        phone=addr.get("phone", ""),
        address=address,
    )
    return contact, address


def order_from_shopify(data: dict, price_from_provider=None, status_mapper=None) -> Order:
    convert = price_from_provider or (lambda x: x)

    items = []
    for item in data.get("line_items", []):
        raw_price = Decimal(str(item.get("price", 0)))
        items.append(OrderItem(
            item_id=str(item.get("id", "")),
            product_id=str(item.get("product_id", "")),
            sku=item.get("sku", ""),
            name=item.get("title", item.get("name", "")),
            quantity=Decimal(str(item.get("quantity", 1))),
            unit_price=convert(raw_price),
        ))

    fulfillment_status = data.get("fulfillment_status") or "unfulfilled"
    raw_status = fulfillment_status

    if status_mapper:
        status = status_mapper.to_framework(raw_status)
    else:
        status = SHOPIFY_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    financial_status = data.get("financial_status", "")
    payment_status = SHOPIFY_FINANCIAL_STATUS_MAP.get(financial_status, PaymentStatus.UNPAID)

    billing_contact, _ = _map_shopify_address(data.get("billing_address"))
    shipping_contact, shipping_addr = _map_shopify_address(data.get("shipping_address"))

    # Customer email
    if billing_contact and data.get("email"):
        billing_contact = billing_contact.model_copy(update={"email": data["email"]})

    total = convert(Decimal(str(data.get("total_price", 0))))

    return Order(
        order_id=str(data.get("order_number", data.get("id", ""))),
        external_id=str(data.get("id", "")),
        status=status,
        raw_status=raw_status,
        payment_status=payment_status,
        currency=data.get("currency", ""),
        items=items,
        billing=billing_contact,
        shipping=shipping_contact,
        shipping_address=shipping_addr,
        total=total,
        created_at=_parse_datetime(data.get("created_at", "")),
        updated_at=_parse_datetime(data.get("updated_at", "")),
        provider_meta=ProviderMeta(
            provider="shopify",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


def orders_from_shopify(response: list[dict], price_from_provider=None, status_mapper=None) -> PaginatedResult[Order]:
    orders = [order_from_shopify(o, price_from_provider=price_from_provider, status_mapper=status_mapper) for o in response]
    return PaginatedResult(
        items=orders,
        has_more=len(response) >= 50,
        total=None,
    )


# ── Category mappers (collections) ──


def category_from_shopify(data: dict) -> ProductCategory:
    return ProductCategory(
        category_id=str(data.get("id", "")),
        name=data.get("title", ""),
    )


# ── Webhook mappers ──


def webhook_event_from_shopify(headers: dict, payload: dict) -> WebhookEvent:
    topic = headers.get("X-Shopify-Topic", headers.get("x-shopify-topic", ""))
    event_type = SHOPIFY_WEBHOOK_MAP.get(topic, WebhookEventType.UNKNOWN)
    webhook_id = headers.get("X-Shopify-Webhook-Id", headers.get("x-shopify-webhook-id", ""))
    return WebhookEvent(
        event_id=webhook_id,
        event_type=event_type,
        provider="shopify",
        provider_event_type=topic,
        payload=payload,
        idempotency_key=webhook_id,
        received_at=datetime.now(UTC),
    )


def verify_shopify_webhook(body: bytes, secret: str, signature: str) -> bool:
    """Verify Shopify HMAC-SHA256 webhook signature."""
    computed = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(signature, computed)
