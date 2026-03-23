"""
Trendyol ↔ DTO mappers.

Converts between raw Trendyol API payloads and normalized framework DTOs.
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

# ── Status mappings ──

TRENDYOL_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "Created": OrderStatus.PENDING,
    "Picking": OrderStatus.PROCESSING,
    "Shipped": OrderStatus.SHIPPED,
    "Delivered": OrderStatus.DELIVERED,
    "Cancelled": OrderStatus.CANCELLED,
    "UnDelivered": OrderStatus.CANCELLED,
}


# ── Order mappers ──


def _map_address(addr: dict | None) -> Address | None:
    if not addr:
        return None
    return Address(
        street=addr.get("fullAddress", "").strip(),
        city=addr.get("city", "").strip(),
        region=addr.get("countyName", "").strip(),
        postal_code=addr.get("postalCode", "").strip(),
        country=addr.get("countryCode", "").upper().strip(),
    )


def _map_contact(addr: dict | None, email: str = "") -> Contact | None:
    if not addr:
        return None
    first = addr.get("firstName", "").strip()
    last = addr.get("lastName", "").strip()
    return Contact(
        name=f"{first} {last}".strip(),
        company_name=addr.get("company", "").strip() if addr.get("company") else "",
        vat_id=addr.get("taxNumber", "").strip() if addr.get("taxNumber") else "",
        email=email.lower().strip() if email else "",
        phone=addr.get("phone", "").strip() if addr.get("phone") else "",
        address=_map_address(addr),
    )


def _format_delivery_address(addr: dict | None) -> str:
    if not addr:
        return ""
    parts = []
    for key in ("fullAddress", "city", "district", "countyName", "postalCode"):
        if val := addr.get(key, ""):
            parts.append(val.strip())
    return ", ".join(parts)


def order_from_trendyol(data: dict) -> Order:
    """Map a Trendyol order response to a normalized Order DTO."""
    items = []
    for line in data.get("lines", []):
        items.append(
            OrderItem(
                item_id=str(line.get("id", "")),
                product_id=line.get("stockCode", ""),
                sku=line.get("stockCode", ""),
                name=line.get("productName", ""),
                quantity=Decimal(str(line.get("quantity", 1))),
                unit_price=Decimal(str(line.get("lineUnitPrice", 0))),
                currency=data.get("currencyCode", "TRY"),
                extra={
                    k: v for k, v in line.items() if k not in ("productName", "stockCode", "quantity", "lineUnitPrice")
                },
            )
        )

    order_date = None
    if ts := data.get("orderDate"):
        order_date = datetime.fromtimestamp(ts / 1000, tz=UTC)

    status = TRENDYOL_ORDER_STATUS_MAP.get(data.get("status", ""), OrderStatus.PENDING)

    return Order(
        order_id=str(data.get("orderNumber", "")),
        external_id=str(data.get("shipmentPackageId", "")) if data.get("shipmentPackageId") else None,
        status=status,
        payment_status=PaymentStatus.PAID if status != OrderStatus.PENDING else PaymentStatus.UNPAID,
        payment_type=PaymentType.ONLINE_CARD,
        currency=data.get("currencyCode", "TRY"),
        items=items,
        billing=_map_contact(data.get("invoiceAddress"), data.get("customerEmail", "")),
        shipping=_map_contact(data.get("shipmentAddress"), data.get("customerEmail", "")),
        shipping_address=_map_address(data.get("shipmentAddress")),
        delivery_address=_format_delivery_address(data.get("shipmentAddress")),
        total=sum(item.unit_price * item.quantity for item in items),
        created_at=order_date,
        external_url=f"https://partner.trendyol.com/ro/orders/shipment-packages/all?orderNumber={data.get('orderNumber', '')}",
        provider_meta=ProviderMeta(
            provider="trendyol",
            raw_id=str(data.get("orderNumber", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "orderNumber",
                "shipmentPackageId",
                "status",
                "currencyCode",
                "customerEmail",
                "invoiceAddress",
                "shipmentAddress",
                "lines",
                "orderDate",
            )
        },
    )


def orders_from_trendyol(response: dict) -> PaginatedResult[Order]:
    """Map a paginated Trendyol orders response to PaginatedResult[Order]."""
    content = response.get("content", [])
    orders = [order_from_trendyol(o) for o in content]
    total_pages = response.get("totalPages", 1)
    page = response.get("page", 0)
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if page + 1 < total_pages else None,
        has_more=page + 1 < total_pages,
        total=response.get("totalElements"),
    )


# ── Product mappers ──


def product_from_trendyol(data: dict) -> Product:
    """Map a Trendyol product response to a normalized Product DTO."""
    return Product(
        product_id=data.get("productMainId", data.get("barcode", "")),
        sku=data.get("stockCode", ""),
        barcode=data.get("barcode", ""),
        name=data.get("title", ""),
        price=Decimal(str(data.get("salePrice", 0))),
        currency="",  # Trendyol doesn't return currency per product
        stock=data.get("quantity"),
        active=not data.get("archived", False),
        provider_meta=ProviderMeta(
            provider="trendyol",
            raw_id=data.get("barcode", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "productMainId",
                "barcode",
                "stockCode",
                "title",
                "salePrice",
                "quantity",
                "archived",
            )
        },
    )


def products_from_trendyol(response: dict) -> PaginatedResult[Product]:
    """Map a paginated Trendyol products response."""
    content = response.get("content", [])
    products = [product_from_trendyol(p) for p in content]
    total_pages = response.get("totalPages", 1)
    page = response.get("page", 0)
    return PaginatedResult(
        items=products,
        cursor=str(page + 1) if page + 1 < total_pages else None,
        has_more=page + 1 < total_pages,
        total=response.get("totalElements"),
    )
