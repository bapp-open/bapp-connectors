"""
eMAG <-> DTO mappers.

Converts between raw eMAG API payloads and normalized framework DTOs.
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
    ProductCategory,
    ProviderMeta,
)
from bapp_connectors.providers.shop.emag.models import EmagApiResponse

# ── Status mappings ──

# eMAG order statuses (numeric):
# 1 = new, 2 = in progress, 3 = prepared, 4 = finalized, 5 = cancelled, 0 = cancelled/storno
EMAG_ORDER_STATUS_MAP: dict[int, OrderStatus] = {
    1: OrderStatus.PENDING,
    2: OrderStatus.PROCESSING,
    3: OrderStatus.PROCESSING,
    4: OrderStatus.DELIVERED,
    5: OrderStatus.CANCELLED,
    0: OrderStatus.CANCELLED,
}

# eMAG payment modes
EMAG_PAYMENT_TYPE_MAP: dict[str, PaymentType] = {
    "online_card": PaymentType.ONLINE_CARD,
    "card": PaymentType.ONLINE_CARD,
    "bank_transfer": PaymentType.BANK_TRANSFER,
    "wire_transfer": PaymentType.BANK_TRANSFER,
    "cash_on_delivery": PaymentType.CASH_ON_DELIVERY,
    "cod": PaymentType.CASH_ON_DELIVERY,
    "ramburs": PaymentType.CASH_ON_DELIVERY,
}


# ── Address / Contact mappers ──


def _map_address(addr: dict | None, country: str = "") -> Address | None:
    if not addr:
        return None
    return Address(
        street=addr.get("street", "").strip(),
        city=addr.get("city", "").strip() or addr.get("locality_name", "").strip(),
        region=addr.get("region", "").strip() or addr.get("county", "").strip(),
        postal_code=addr.get("zipcode", "").strip() or addr.get("postal_code", "").strip(),
        country=addr.get("country", country).upper().strip(),
    )


def _map_contact(addr: dict | None, customer: dict | None = None, country: str = "") -> Contact | None:
    if not addr and not customer:
        return None

    addr = addr or {}
    customer = customer or {}

    name = addr.get("name", "").strip() or customer.get("name", "").strip()
    company = addr.get("company", "").strip() or customer.get("company", "").strip()
    phone = addr.get("phone", "").strip() or customer.get("phone_1", "").strip()
    email = customer.get("email", "").lower().strip()

    return Contact(
        name=name,
        company_name=company,
        vat_id=addr.get("fiscal_code", "").strip() if addr.get("fiscal_code") else "",
        email=email,
        phone=phone,
        address=_map_address(addr, country),
    )


def _format_delivery_address(addr: dict | None) -> str:
    """Build a human-readable delivery address string."""
    if not addr:
        return ""
    parts = []
    for key in ("street", "city", "locality_name", "county", "region", "zipcode"):
        if val := addr.get(key, ""):
            parts.append(val.strip())
    return ", ".join(parts)


# ── Order mappers ──


def order_from_emag(data: dict, country: str = "RO") -> Order:
    """Map an eMAG order response to a normalized Order DTO."""
    items = []
    for line in data.get("products", []):
        items.append(
            OrderItem(
                item_id=str(line.get("id", "")),
                product_id=line.get("part_number", ""),
                sku=line.get("part_number_key", line.get("part_number", "")),
                name=line.get("product_name", ""),
                quantity=Decimal(str(line.get("quantity", 1))),
                unit_price=Decimal(str(line.get("sale_price", 0))),
                currency=line.get("currency", "RON"),
                tax_rate=Decimal(str(line.get("vat", 0))) if line.get("vat") is not None else None,
                extra={
                    k: v
                    for k, v in line.items()
                    if k
                    not in (
                        "id",
                        "part_number",
                        "part_number_key",
                        "product_name",
                        "quantity",
                        "sale_price",
                        "currency",
                        "vat",
                    )
                },
            )
        )

    order_date = None
    if date_str := data.get("date"):
        with contextlib.suppress(ValueError, TypeError):
            order_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    raw_status = data.get("status", 1)
    status = EMAG_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    # Payment type
    payment_mode = data.get("payment_mode", "").lower().strip()
    payment_type = EMAG_PAYMENT_TYPE_MAP.get(payment_mode, PaymentType.OTHER)

    # Payment status: eMAG payment_status field (0=unpaid, 1=paid)
    raw_payment_status = data.get("payment_status", 0)
    payment_status = PaymentStatus.PAID if raw_payment_status == 1 else PaymentStatus.UNPAID

    # Calculate total
    total = sum(item.unit_price * item.quantity for item in items)
    if shipping_tax := data.get("shipping_tax"):
        total += Decimal(str(shipping_tax))

    # Determine currency from items or default
    currency = items[0].currency if items else "RON"

    emag_id = str(data.get("id", ""))

    return Order(
        order_id=emag_id,
        external_id=emag_id,
        status=status,
        payment_status=payment_status,
        payment_type=payment_type,
        currency=currency,
        items=items,
        billing=_map_contact(data.get("billing_address"), data.get("customer"), country),
        shipping=_map_contact(data.get("delivery_address"), data.get("customer"), country),
        shipping_address=_map_address(data.get("delivery_address"), country),
        delivery_address=_format_delivery_address(data.get("delivery_address")),
        total=total,
        created_at=order_date,
        external_url=f"https://marketplace.emag.{country.lower()}/order/details/id/{emag_id}",
        provider_meta=ProviderMeta(
            provider="emag",
            raw_id=emag_id,
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
                "payment_mode",
                "payment_mode_id",
                "payment_status",
                "customer",
                "products",
                "date",
                "billing_address",
                "delivery_address",
                "shipping_tax",
            )
        },
    )


def orders_from_emag(response: EmagApiResponse, country: str = "RO") -> PaginatedResult[Order]:
    """Map a paginated eMAG orders response to PaginatedResult[Order]."""
    orders = [order_from_emag(o, country) for o in response.results]
    current_page = response.current_page
    total_pages = response.no_of_pages
    return PaginatedResult(
        items=orders,
        cursor=str(current_page + 1) if current_page < total_pages else None,
        has_more=current_page < total_pages,
        total=response.no_of_items,
    )


# ── Product mappers ──


def product_from_emag(data: dict) -> Product:
    """Map an eMAG product offer response to a normalized Product DTO."""
    # Calculate total stock across warehouses
    total_stock = 0
    for entry in data.get("stock", []):
        val = entry.get("value", 0)
        if isinstance(val, (int, float)):
            total_stock += int(val)

    ean_list = data.get("ean", [])
    barcode = ean_list[0] if ean_list else ""

    return Product(
        product_id=data.get("part_number", str(data.get("id", ""))),
        sku=data.get("part_number_key", data.get("part_number", "")),
        barcode=barcode,
        name=data.get("name", ""),
        description=data.get("description", ""),
        price=Decimal(str(data.get("sale_price", 0))),
        currency=data.get("currency_code", "RON"),
        stock=total_stock,
        active=data.get("status", 0) == 1,
        provider_meta=ProviderMeta(
            provider="emag",
            raw_id=data.get("part_number", str(data.get("id", ""))),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "id",
                "part_number",
                "part_number_key",
                "name",
                "description",
                "sale_price",
                "currency_code",
                "stock",
                "status",
                "ean",
            )
        },
    )


def products_from_emag(response: EmagApiResponse) -> PaginatedResult[Product]:
    """Map a paginated eMAG products response."""
    products = [product_from_emag(p) for p in response.results]
    current_page = response.current_page
    total_pages = response.no_of_pages
    return PaginatedResult(
        items=products,
        cursor=str(current_page + 1) if current_page < total_pages else None,
        has_more=current_page < total_pages,
        total=response.no_of_items,
    )


# ── Category mapper ──


def categories_from_emag(response: EmagApiResponse) -> list[ProductCategory]:
    """Map eMAG category response to normalized ProductCategory DTOs."""
    categories = []
    for cat in response.results:
        categories.append(
            ProductCategory(
                category_id=str(cat.get("id", "")),
                name=cat.get("name", ""),
                parent_id=str(cat["parent_id"]) if cat.get("parent_id") else None,
                extra={k: v for k, v in cat.items() if k not in ("id", "name", "parent_id")},
            )
        )
    return categories
