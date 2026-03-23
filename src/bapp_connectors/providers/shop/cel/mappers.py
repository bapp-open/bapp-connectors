"""
CEL.ro <-> DTO mappers.

Converts between raw CEL API payloads and normalized framework DTOs.
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

CEL_ORDER_STATUS_MAP: dict[int, OrderStatus] = {
    0: OrderStatus.CANCELLED,
    1: OrderStatus.PENDING,
    2: OrderStatus.PROCESSING,
    3: OrderStatus.SHIPPED,
    4: OrderStatus.DELIVERED,
}

CEL_PAYMENT_TYPE_MAP: dict[int, PaymentType] = {
    1: PaymentType.CASH_ON_DELIVERY,
    2: PaymentType.BANK_TRANSFER,
    3: PaymentType.ONLINE_CARD,
    4: PaymentType.PAYMENT_ORDER,
}

# ── Language mapping ──

COUNTRY_LANGUAGES: dict[str, str] = {
    "RO": "RO",
    "BG": "BG",
    "HU": "HU",
}


# ── Order mappers ──


def _map_address(customer: dict) -> Address | None:
    if not customer:
        return None
    return Address(
        street=customer.get("shipping_street", "").strip(),
        country=customer.get("shipping_country", "").upper().strip(),
    )


def _map_billing_contact(customer: dict) -> Contact | None:
    if not customer:
        return None
    first = customer.get("firstname", "").strip()
    last = customer.get("lastname", "").strip()
    return Contact(
        name=f"{first} {last}".strip(),
        company_name=customer.get("company", "").strip() if customer.get("company") else "",
        vat_id=customer.get("vat_number", "").strip() if customer.get("vat_number") else "",
        email=customer.get("email", "").lower().strip() if customer.get("email") else "",
        phone=customer.get("phone", "").strip() if customer.get("phone") else "",
        address=Address(
            street=customer.get("billing_street", "").strip(),
            country=customer.get("billing_country", "").upper().strip(),
        ),
    )


def _map_shipping_contact(customer: dict) -> Contact | None:
    if not customer:
        return None
    first = customer.get("firstname", "").strip()
    last = customer.get("lastname", "").strip()
    return Contact(
        name=f"{first} {last}".strip(),
        email=customer.get("email", "").lower().strip() if customer.get("email") else "",
        phone=customer.get("phone", "").strip() if customer.get("phone") else "",
        address=_map_address(customer),
    )


def _format_delivery_address(customer: dict) -> str:
    if not customer:
        return ""
    return customer.get("shipping_street", "").strip()


def order_from_cel(data: dict) -> Order:
    """Map a CEL order response to a normalized Order DTO."""
    items = []
    currency = "RON"
    for product in data.get("products", []):
        if product.get("currency"):
            currency = product["currency"].upper()
        items.append(
            OrderItem(
                item_id=str(product.get("sku", "")),
                product_id=product.get("sku", ""),
                sku=product.get("sku", ""),
                name=product.get("name", ""),
                quantity=Decimal(str(product.get("quantity", 1))),
                unit_price=Decimal(str(product.get("price", 0))),
                currency=product.get("currency", "RON"),
            )
        )

    order_date = None
    if date_str := data.get("date"):
        order_date = _parse_datetime(date_str)

    raw_status = data.get("status", 1)
    status = CEL_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)
    payment_type = CEL_PAYMENT_TYPE_MAP.get(data.get("payment_mode_id", 0), PaymentType.OTHER)

    customer = data.get("customer", {})

    return Order(
        order_id=str(data.get("order_id", data.get("id", ""))),
        external_id=str(data.get("id", "")) if data.get("id") else None,
        status=status,
        payment_status=PaymentStatus.PAID if status != OrderStatus.PENDING else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency=currency,
        items=items,
        billing=_map_billing_contact(customer),
        shipping=_map_shipping_contact(customer),
        shipping_address=_map_address(customer),
        delivery_address=_format_delivery_address(customer),
        total=sum(item.unit_price * item.quantity for item in items),
        created_at=order_date,
        provider_meta=ProviderMeta(
            provider="cel",
            raw_id=str(data.get("order_id", data.get("id", ""))),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k not in ("order_id", "id", "status", "date", "payment_mode_id", "customer", "products")
        },
    )


def orders_from_cel(results: list[dict]) -> PaginatedResult[Order]:
    """Map a list of CEL order results to PaginatedResult[Order]."""
    orders = [order_from_cel(o) for o in results]
    return PaginatedResult(
        items=orders,
        cursor=None,
        has_more=False,
        total=len(orders),
    )


# ── Product mappers ──


def product_from_cel(data: dict) -> Product:
    """Map a CEL product response to a normalized Product DTO."""
    return Product(
        product_id=data.get("sku", data.get("id", "")),
        sku=data.get("sku", ""),
        barcode=data.get("ean", ""),
        name=data.get("name", ""),
        price=Decimal(str(data.get("price", 0))) if data.get("price") else None,
        currency=data.get("currency", "RON"),
        stock=data.get("stock") if data.get("stock") is not None else None,
        active=True,
        provider_meta=ProviderMeta(
            provider="cel",
            raw_id=str(data.get("sku", data.get("id", ""))),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={k: v for k, v in data.items() if k not in ("sku", "id", "ean", "name", "price", "currency", "stock")},
    )


def products_from_cel(results: list[dict]) -> PaginatedResult[Product]:
    """Map a list of CEL product results to PaginatedResult[Product]."""
    products = [product_from_cel(p) for p in results]
    return PaginatedResult(
        items=products,
        cursor=None,
        has_more=False,
        total=len(products),
    )
