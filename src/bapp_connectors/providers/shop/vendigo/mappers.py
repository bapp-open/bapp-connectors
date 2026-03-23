"""
Vendigo <-> DTO mappers.

Converts between raw Vendigo API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

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
    ProviderMeta,
)


def _parse_datetime(value: str) -> datetime | None:
    """Parse ISO datetime string without dateutil dependency."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


# ── Status mappings ──

VENDIGO_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "pending": OrderStatus.PENDING,
    "received": OrderStatus.ACCEPTED,
    "delivered": OrderStatus.DELIVERED,
    "canceled": OrderStatus.CANCELLED,
}

# Payment option IDs from the legacy system
VENDIGO_PAYMENT_TYPE_MAP: dict[int, PaymentType] = {
    35385: PaymentType.PAYMENT_ORDER,
    8429: PaymentType.CASH_ON_DELIVERY,
}


# ── Order mappers ──


def _parse_price(price_str: str) -> Decimal:
    """Parse a Vendigo price string like '123,45 lei' into a Decimal."""
    cleaned = price_str.replace("lei", "").replace(",", ".").strip()
    if not cleaned:
        return Decimal("0")
    return Decimal(cleaned)


def _map_contact(data: dict) -> Contact | None:
    if not data:
        return None

    first = data.get("client_first_name", "").strip()
    last = data.get("client_last_name", "").strip()
    name = f"{first} {last}".strip()

    delivery_addr = data.get("delivery_address", "")
    region = delivery_addr.split(",")[0].strip() if delivery_addr else ""

    return Contact(
        name=name,
        company_name=data.get("company", "").strip(),
        vat_id=data.get("cui", "").strip(),
        email=data.get("email", "").lower().strip() if data.get("email") else "",
        phone=data.get("phone", "").strip() if data.get("phone") else "",
        address=Address(
            street=delivery_addr,
            region=region,
            country="RO",
        ),
    )


def _format_delivery_address(data: dict) -> str:
    return data.get("delivery_address", "")


def order_from_vendigo(data: dict) -> Order:
    """Map a Vendigo order response to a normalized Order DTO."""
    items = []
    for product in data.get("products", []):
        items.append(
            OrderItem(
                item_id=product.get("sku", ""),
                product_id=product.get("sku", ""),
                sku=product.get("sku", ""),
                name=product.get("name", ""),
                quantity=Decimal(str(product.get("quantity", 1))),
                unit_price=_parse_price(str(product.get("price", "0"))),
                currency="RON",
            )
        )

    # Shipping cost as an extra line item
    shipping_cost = Decimal(str(data.get("delivery_cost", "0")))
    if shipping_cost:
        items.append(
            OrderItem(
                item_id="shipping",
                name="Taxe de livrare",
                quantity=Decimal("1"),
                unit_price=shipping_cost,
                currency="RON",
                extra={"is_transport": True},
            )
        )

    order_date = None
    if date_str := data.get("date_created"):
        try:
            order_date = _parse_datetime(date_str)
            if order_date.tzinfo is None:
                order_date = order_date.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pass

    status = VENDIGO_ORDER_STATUS_MAP.get(data.get("status", ""), OrderStatus.PENDING)

    # Payment type from payment option ID
    payment_type = PaymentType.PAYMENT_ORDER
    if (payment_option := data.get("payment_option")) and isinstance(payment_option, dict):
        option_id = payment_option.get("id")
        if option_id:
            payment_type = VENDIGO_PAYMENT_TYPE_MAP.get(option_id, PaymentType.PAYMENT_ORDER)

    order_id = str(data.get("id", ""))

    return Order(
        order_id=order_id,
        status=status,
        payment_status=PaymentStatus.PAID if status != OrderStatus.PENDING else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency="RON",
        items=items,
        billing=_map_contact(data),
        shipping=_map_contact(data),
        shipping_address=Address(
            street=data.get("delivery_address", ""),
            country="RO",
        ),
        delivery_address=_format_delivery_address(data),
        total=sum(item.unit_price * item.quantity for item in items),
        created_at=order_date,
        provider_meta=ProviderMeta(
            provider="vendigo",
            raw_id=order_id,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "id",
                "status",
                "date_created",
                "client_first_name",
                "client_last_name",
                "email",
                "phone",
                "delivery_address",
                "delivery_cost",
                "products",
                "payment_option",
                "company",
                "cui",
            )
        },
    )


def orders_from_vendigo(orders_list: list[dict]) -> PaginatedResult[Order]:
    """Map a list of Vendigo orders to PaginatedResult[Order]."""
    orders = [order_from_vendigo(o) for o in orders_list]
    return PaginatedResult(
        items=orders,
        cursor=None,
        has_more=False,
        total=len(orders),
    )


# ── Product mappers ──


def product_from_vendigo(data: dict) -> Product:
    """Map a Vendigo product response to a normalized Product DTO."""
    return Product(
        product_id=str(data.get("external_id", data.get("id", ""))),
        sku=data.get("sku", ""),
        name=data.get("name", ""),
        price=Decimal(str(data.get("price", 0))),
        currency="RON",
        stock=data.get("stock"),
        active=True,
        provider_meta=ProviderMeta(
            provider="vendigo",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={k: v for k, v in data.items() if k not in ("id", "external_id", "sku", "name", "price", "stock")},
    )


def products_from_vendigo(products_list: list[dict]) -> PaginatedResult[Product]:
    """Map a list of Vendigo products to PaginatedResult[Product]."""
    products = [product_from_vendigo(p) for p in products_list]
    return PaginatedResult(
        items=products,
        cursor=None,
        has_more=False,
        total=len(products),
    )
