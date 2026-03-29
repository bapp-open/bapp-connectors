"""
Gomag <-> DTO mappers.

Converts between raw Gomag API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.

IMPORTANT: The Gomag API returns products as a dict keyed by product ID,
not as a list. The normalization to list happens here.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

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
)

if TYPE_CHECKING:
    from bapp_connectors.core.status_mapping import StatusMapper

# ── Status mappings (defaults — tenants can override via connection config) ──

GOMAG_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "Comanda NEW": OrderStatus.PENDING,
    "Comanda email": OrderStatus.PENDING,
    "Comanda telefonica": OrderStatus.PENDING,
    "Comanda in asteptare": OrderStatus.PENDING,
    "Comanda depozitata": OrderStatus.ACCEPTED,
    "Comanda depozit": OrderStatus.ACCEPTED,
    "In curs de procesare": OrderStatus.PROCESSING,
    "Comanda in curs de livrare": OrderStatus.SHIPPED,
    "Livrata": OrderStatus.DELIVERED,
    "Comanda incheiata": OrderStatus.DELIVERED,
    "Anulata": OrderStatus.CANCELLED,
    "Retur": OrderStatus.RETURNED,
    "Returnata": OrderStatus.RETURNED,
}

ORDER_STATUS_TO_GOMAG: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "Comanda NEW",
    OrderStatus.ACCEPTED: "Comanda depozitata",
    OrderStatus.PROCESSING: "In curs de procesare",
    OrderStatus.SHIPPED: "Comanda in curs de livrare",
    OrderStatus.DELIVERED: "Livrata",
    OrderStatus.CANCELLED: "Anulata",
    OrderStatus.RETURNED: "Retur",
    OrderStatus.REFUNDED: "Retur",
}

GOMAG_PAYMENT_METHOD_MAP: dict[str, PaymentType] = {
    "Plata ramburs": PaymentType.CASH_ON_DELIVERY,
    "Ordin de Plata": PaymentType.BANK_TRANSFER,
    "Plata cu cardul": PaymentType.ONLINE_CARD,
    "Card online": PaymentType.ONLINE_CARD,
}


# ── Address / Contact mappers ──


def _map_billing_address(data: dict) -> Address | None:
    street_parts = [data.get("payment_address_1", ""), data.get("payment_address_2", "")]
    street = ", ".join(p.strip() for p in street_parts if p.strip())
    if not street and not data.get("payment_city"):
        return None
    return Address(
        street=street,
        city=data.get("payment_city", "").strip(),
        region=data.get("payment_zone", "").strip(),
        postal_code=data.get("payment_postcode", "").strip(),
        country=data.get("payment_country", "").upper().strip(),
    )


def _map_shipping_address(data: dict) -> Address | None:
    street_parts = [data.get("shipping_address_1", ""), data.get("shipping_address_2", "")]
    street = ", ".join(p.strip() for p in street_parts if p.strip())
    if not street and not data.get("shipping_city"):
        return None
    return Address(
        street=street,
        city=data.get("shipping_city", "").strip(),
        region=data.get("shipping_zone", "").strip(),
        postal_code=data.get("shipping_postcode", "").strip(),
        country=data.get("shipping_country", "").upper().strip(),
    )


def _map_billing_contact(data: dict) -> Contact | None:
    first = data.get("payment_firstname", data.get("firstname", "")).strip()
    last = data.get("payment_lastname", data.get("lastname", "")).strip()
    name = f"{first} {last}".strip()
    if not name:
        return None
    return Contact(
        name=name,
        company_name=data.get("payment_company", data.get("company", "")).strip(),
        email=data.get("email", "").lower().strip() if data.get("email") else "",
        phone=data.get("telephone", "").strip() if data.get("telephone") else "",
        address=_map_billing_address(data),
    )


def _map_shipping_contact(data: dict) -> Contact | None:
    first = data.get("shipping_firstname", "").strip()
    last = data.get("shipping_lastname", "").strip()
    name = f"{first} {last}".strip()
    if not name:
        return None
    return Contact(
        name=name,
        company_name=data.get("shipping_company", "").strip(),
        email=data.get("email", "").lower().strip() if data.get("email") else "",
        phone=data.get("telephone", "").strip() if data.get("telephone") else "",
        address=_map_shipping_address(data),
    )


def _format_delivery_address(data: dict) -> str:
    parts = []
    for key in (
        "shipping_address_1",
        "shipping_address_2",
        "shipping_city",
        "shipping_zone",
        "shipping_postcode",
        "shipping_country",
    ):
        if val := data.get(key, ""):
            parts.append(val.strip())
    return ", ".join(parts)


# ── Order mappers ──


def order_from_gomag(data: dict, *, status_mapper: StatusMapper | None = None) -> Order:
    """Map a Gomag order response to a normalized Order DTO."""
    items = []
    for line in data.get("products", []):
        items.append(
            OrderItem(
                item_id=str(line.get("product_id", "")),
                product_id=str(line.get("product_id", "")),
                sku=line.get("sku", line.get("model", "")),
                name=line.get("product_name", line.get("name", "")),
                quantity=Decimal(str(line.get("quantity", 1))),
                unit_price=Decimal(str(line.get("price", 0))),
                currency=data.get("currency_code", "RON"),
                extra={
                    k: v
                    for k, v in line.items()
                    if k not in ("product_id", "sku", "model", "product_name", "name", "quantity", "price")
                },
            )
        )

    order_date = None
    if ds := data.get("date_added"):
        try:
            order_date = datetime.fromisoformat(ds.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            with contextlib.suppress(ValueError, AttributeError):
                order_date = datetime.strptime(ds, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    raw_status = data.get("status_name", data.get("status", ""))
    if status_mapper:
        status = status_mapper.to_framework(raw_status)
    else:
        status = GOMAG_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    payment_method = data.get("payment_method", "")
    payment_type = GOMAG_PAYMENT_METHOD_MAP.get(payment_method, PaymentType.OTHER)

    total = Decimal(str(data.get("total", 0)))

    return Order(
        order_id=str(data.get("order_id", "")),
        external_id=str(data.get("order_id", "")) if data.get("order_id") else None,
        status=status,
        raw_status=raw_status,
        payment_status=PaymentStatus.PAID if status == OrderStatus.DELIVERED else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency=data.get("currency_code", "RON"),
        items=items,
        billing=_map_billing_contact(data),
        shipping=_map_shipping_contact(data),
        shipping_address=_map_shipping_address(data),
        delivery_address=_format_delivery_address(data),
        total=total,
        created_at=order_date,
        provider_meta=ProviderMeta(
            provider="gomag",
            raw_id=str(data.get("order_id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "order_id",
                "status_name",
                "status",
                "currency_code",
                "date_added",
                "total",
                "payment_method",
                "firstname",
                "lastname",
                "email",
                "telephone",
                "company",
                "payment_firstname",
                "payment_lastname",
                "payment_company",
                "payment_address_1",
                "payment_address_2",
                "payment_city",
                "payment_zone",
                "payment_postcode",
                "payment_country",
                "shipping_firstname",
                "shipping_lastname",
                "shipping_company",
                "shipping_address_1",
                "shipping_address_2",
                "shipping_city",
                "shipping_zone",
                "shipping_postcode",
                "shipping_country",
                "products",
            )
        },
    )


def _normalize_gomag_list(response: dict | list, key: str = "") -> list[dict]:
    """
    Normalize Gomag API response to a list of dicts.

    Gomag returns products (and sometimes orders) as a dict keyed by ID
    instead of a list. This function handles both cases.
    """
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        # If there's a specific key, try extracting from it
        if key and key in response:
            data = response[key]
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return list(data.values())
        # The response itself is a dict of items keyed by ID
        # Filter out metadata keys that aren't item dicts
        items = []
        for v in response.values():
            if isinstance(v, dict):
                items.append(v)
        return items
    return []


def orders_from_gomag(
    response: dict | list, page: int = 1, *, status_mapper: StatusMapper | None = None
) -> PaginatedResult[Order]:
    """Map a Gomag orders response to PaginatedResult[Order]."""
    raw_orders = _normalize_gomag_list(response)
    orders = [order_from_gomag(o, status_mapper=status_mapper) for o in raw_orders]
    has_more = len(raw_orders) > 0 and len(raw_orders) >= 100
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


# ── Product mappers ──


def product_from_gomag(data: dict) -> Product:
    """Map a Gomag product response to a normalized Product DTO."""
    photos = []
    if image_url := data.get("image", ""):
        photos.append(ProductPhoto(url=image_url, position=0))

    price = None
    if raw_price := data.get("price"):
        with contextlib.suppress(Exception):
            price = Decimal(str(raw_price))

    categories = []
    if cat := data.get("category", ""):
        categories.append(str(cat))

    return Product(
        product_id=str(data.get("product_id", "")),
        sku=data.get("sku", data.get("model", "")),
        name=data.get("name", ""),
        description=data.get("description", ""),
        price=price,
        currency="",  # Gomag doesn't return currency per product
        stock=int(data["quantity"]) if data.get("quantity") is not None else None,
        active=str(data.get("status", "1")) == "1",
        categories=categories,
        photos=photos,
        provider_meta=ProviderMeta(
            provider="gomag",
            raw_id=str(data.get("product_id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "product_id",
                "sku",
                "model",
                "name",
                "description",
                "price",
                "quantity",
                "status",
                "category",
                "image",
            )
        },
    )


def products_from_gomag(response: dict | list, page: int = 1) -> PaginatedResult[Product]:
    """Map a Gomag products response to PaginatedResult[Product].

    IMPORTANT: Gomag returns products as a dict keyed by product ID,
    not as a list. We normalize this here.
    """
    raw_products = _normalize_gomag_list(response)
    products = [product_from_gomag(p) for p in raw_products]
    has_more = len(raw_products) > 0 and len(raw_products) >= 100
    return PaginatedResult(
        items=products,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )
