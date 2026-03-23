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
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    PaymentType,
    Product,
    ProductPhoto,
    ProviderMeta,
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


def order_from_woocommerce(data: dict) -> Order:
    """Map a WooCommerce order response to a normalized Order DTO."""
    items = []
    for line in data.get("line_items", []):
        items.append(
            OrderItem(
                item_id=str(line.get("id", "")),
                product_id=str(line.get("product_id", "")),
                sku=line.get("sku", ""),
                name=line.get("name", ""),
                quantity=Decimal(str(line.get("quantity", 1))),
                unit_price=Decimal(str(line.get("price", 0))),
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
    status = WOO_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    payment_method = data.get("payment_method", "")
    payment_type = WOO_PAYMENT_METHOD_MAP.get(payment_method, PaymentType.OTHER)

    total = Decimal(str(data.get("total", 0)))

    return Order(
        order_id=str(data.get("number", data.get("id", ""))),
        external_id=str(data.get("id", "")) if data.get("id") else None,
        status=status,
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


def orders_from_woocommerce(response: list[dict], page: int = 1) -> PaginatedResult[Order]:
    """Map a WooCommerce orders list response to PaginatedResult[Order]."""
    orders = [order_from_woocommerce(o) for o in response]
    has_more = len(response) > 0 and len(response) >= 100
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


# ── Product mappers ──


def product_from_woocommerce(data: dict) -> Product:
    """Map a WooCommerce product response to a normalized Product DTO."""
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
            price = Decimal(str(raw_price))

    categories = [str(cat.get("name", "")) for cat in data.get("categories", [])]

    return Product(
        product_id=str(data.get("id", "")),
        sku=data.get("sku", ""),
        name=data.get("name", ""),
        description=data.get("description", ""),
        price=price,
        currency="",  # WooCommerce doesn't return currency per product
        stock=data.get("stock_quantity"),
        active=data.get("status", "") == "publish",
        categories=categories,
        photos=photos,
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


def products_from_woocommerce(response: list[dict], page: int = 1) -> PaginatedResult[Product]:
    """Map a WooCommerce products list response to PaginatedResult[Product]."""
    products = [product_from_woocommerce(p) for p in response]
    has_more = len(response) > 0 and len(response) >= 100
    return PaginatedResult(
        items=products,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


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
