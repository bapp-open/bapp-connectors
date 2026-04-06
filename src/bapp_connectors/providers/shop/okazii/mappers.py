"""
Okazii <-> DTO mappers.

Converts between raw Okazii API payloads and normalized framework DTOs.
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
    # Handle timezone offset (+00:00, +03:00, etc.) by converting to Z
    if "+" in value[10:]:
        value = value[: value.rindex("+")] + "Z"
    elif value.endswith("Z"):
        pass  # already UTC
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


# ── Status mappings ──

OKAZII_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.PENDING,
    "confirmed": OrderStatus.ACCEPTED,
    "delivered": OrderStatus.DELIVERED,
    "finished": OrderStatus.DELIVERED,
    "canceled": OrderStatus.CANCELLED,
    "returned": OrderStatus.RETURNED,
}

ORDER_STATUS_TO_OKAZII: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "new",
    OrderStatus.ACCEPTED: "confirmed",
    OrderStatus.PROCESSING: "confirmed",
    OrderStatus.SHIPPED: "confirmed",
    OrderStatus.DELIVERED: "delivered",
    OrderStatus.CANCELLED: "canceled",
    OrderStatus.RETURNED: "returned",
    OrderStatus.REFUNDED: "returned",
}

OKAZII_PAYMENT_TYPE_MAP: dict[str, PaymentType] = {
    "card": PaymentType.ONLINE_CARD,
    "ramburs_okazii": PaymentType.CASH_ON_DELIVERY,
    "ramburs": PaymentType.CASH_ON_DELIVERY,
    "predare_personala": PaymentType.OTHER,
    "avans": PaymentType.BANK_TRANSFER,
}


# ── Order mappers ──


def _map_delivery_address(addr: dict | None) -> Address | None:
    if not addr:
        return None
    return Address(
        street=addr.get("street", ""),
        city=addr.get("city", ""),
        region=addr.get("county", ""),
        postal_code=addr.get("zipcode", ""),
        country=addr.get("country", "RO"),
    )


def _format_delivery_address(addr: dict | None) -> str:
    """Format a delivery address dict into a single string."""
    if not addr:
        return ""
    parts = []
    if street := addr.get("street", ""):
        parts.append(street)
    if street_nr := addr.get("streetNr", ""):
        parts.append(street_nr)
    city = addr.get("city", "")
    county = addr.get("county", "")
    if city or county:
        location = f"{city},{county}" if city and county else city or county
        parts.append(location)
    if zipcode := addr.get("zipcode", ""):
        parts.append(f"({zipcode})")
    return " ".join(parts)


def _map_billing_contact(data: dict) -> Contact | None:
    """Map billing info from an Okazii order to a Contact DTO."""
    billing_info = data.get("billingInfo") or data.get("deliveryAddress")
    buyer_contact = data.get("buyerContact", {})
    if not billing_info:
        return None

    first_name = billing_info.get("firstName", "") or buyer_contact.get("firstName", "")
    last_name = billing_info.get("lastName", "") or buyer_contact.get("lastName", "")

    # Build invoice address — prefer 'address' (already formatted) over street+streetNr
    if full_addr := billing_info.get("address", ""):
        invoice_address = full_addr.strip()
    else:
        invoice_parts = []
        if street := billing_info.get("street", ""):
            invoice_parts.append(street)
        if street_nr := billing_info.get("streetNr", ""):
            invoice_parts.append(street_nr)
        invoice_address = " ".join(invoice_parts)

    return Contact(
        name=f"{first_name} {last_name}".strip(),
        company_name=billing_info.get("company", "").strip(),
        vat_id=billing_info.get("cui", "").strip(),
        email=buyer_contact.get("email", "").lower().strip() if buyer_contact.get("email") else "",
        phone=buyer_contact.get("phone", "").strip() if buyer_contact.get("phone") else "",
        address=Address(
            street=invoice_address,
            city=billing_info.get("city", ""),
            region=billing_info.get("county", ""),
            postal_code=billing_info.get("zipcode", ""),
            country="RO",
        ),
    )


def _map_shipping_contact(data: dict) -> Contact | None:
    """Map shipping info from an Okazii order to a Contact DTO."""
    delivery_address = data.get("deliveryAddress")
    buyer_contact = data.get("buyerContact", {})
    if not delivery_address:
        return None

    return Contact(
        name=f"{buyer_contact.get('firstName', '')} {buyer_contact.get('lastName', '')}".strip(),
        email=buyer_contact.get("email", "").lower().strip() if buyer_contact.get("email") else "",
        phone=buyer_contact.get("phone", "").strip() if buyer_contact.get("phone") else "",
        address=_map_delivery_address(delivery_address),
    )


def order_from_okazii(data: dict) -> Order:
    """Map an Okazii order response to a normalized Order DTO."""
    items = []
    bids = data.get("bids", [])

    for bid in bids:
        item_price = bid.get("itemPrice", {})
        unique_id = str(bid.get("auctionUniqueId", ""))
        items.append(
            OrderItem(
                item_id=str(bid.get("bidId", unique_id)),
                product_id=unique_id,
                sku=bid.get("auctionSku") or unique_id,
                name=bid.get("auctionTitle", ""),
                quantity=Decimal(str(bid.get("amount", 1))),
                unit_price=Decimal(str(item_price.get("amount", 0))),
                currency=item_price.get("currency", "RON"),
                extra={
                    k: v
                    for k, v in bid.items()
                    if k not in (
                        "bidId", "auctionUniqueId", "auctionSku", "auctionTitle",
                        "amount", "itemPrice", "@type",
                    )
                },
            )
        )

    # Shipping cost
    delivery_price = data.get("deliveryPrice", {})
    if delivery_price:
        shipping_amount = Decimal(str(delivery_price.get("amount", "0")))
        if shipping_amount:
            items.append(
                OrderItem(
                    item_id="shipping",
                    name="Taxe de livrare",
                    quantity=Decimal("1"),
                    unit_price=shipping_amount,
                    currency=delivery_price.get("currency", "RON"),
                    extra={"is_transport": True},
                )
            )

    order_date = _parse_datetime(data.get("createdAt", ""))
    updated_at = _parse_datetime(data.get("updatedAt", ""))

    # Status from first bid
    raw_status = bids[0].get("status", "") if bids else ""
    status = OKAZII_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    # Payment type from first bid
    payment_method = bids[0].get("paymentMethod", "") if bids else ""
    payment_type = OKAZII_PAYMENT_TYPE_MAP.get(payment_method, PaymentType.OTHER)

    order_id = str(data.get("id", ""))
    delivery_addr = data.get("deliveryAddress", {})

    # Use API-provided total when available
    total_value = data.get("totalValue", {})
    total = Decimal(str(total_value["amount"])) if total_value.get("amount") is not None else sum(
        item.unit_price * item.quantity for item in items
    )
    currency = total_value.get("currency", "RON") if total_value else "RON"

    return Order(
        order_id=order_id,
        status=status,
        raw_status=raw_status,
        payment_status=PaymentStatus.PAID if status != OrderStatus.PENDING else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency=currency,
        items=items,
        billing=_map_billing_contact(data),
        shipping=_map_shipping_contact(data),
        shipping_address=_map_delivery_address(delivery_addr),
        delivery_address=_format_delivery_address(delivery_addr),
        total=total,
        created_at=order_date,
        updated_at=updated_at,
        provider_meta=ProviderMeta(
            provider="okazii",
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
                "createdAt",
                "updatedAt",
                "bids",
                "deliveryAddress",
                "deliveryPrice",
                "billingInfo",
                "buyerContact",
                "totalValue",
                "@context",
                "@id",
                "@type",
            )
        },
    )


def orders_from_okazii(orders_list: list[dict]) -> PaginatedResult[Order]:
    """Map a list of Okazii orders to PaginatedResult[Order]."""
    orders = [order_from_okazii(o) for o in orders_list]
    return PaginatedResult(
        items=orders,
        cursor=None,
        has_more=False,
        total=len(orders),
    )


# ── Product mappers ──
# Okazii uses product feed (XML/CSV) for product management, not a REST API.
# Mapping functions are provided for consistency, though products are typically
# pushed via feed rather than pulled via API.


def product_from_okazii(data: dict) -> Product:
    """Map an Okazii product response to a normalized Product DTO."""
    return Product(
        product_id=str(data.get("id", "")),
        sku=str(data.get("id", "")),
        name=data.get("title", ""),
        description=data.get("description", ""),
        price=Decimal(str(data.get("price", 0))),
        currency=data.get("currency", "RON"),
        stock=data.get("amount"),
        active=bool(data.get("IN_STOCK", True)),
        provider_meta=ProviderMeta(
            provider="okazii",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k not in ("id", "title", "description", "price", "currency", "amount", "IN_STOCK")
        },
    )


def products_from_okazii(products_list: list[dict]) -> PaginatedResult[Product]:
    """Map a list of Okazii products to PaginatedResult[Product]."""
    products = [product_from_okazii(p) for p in products_list]
    return PaginatedResult(
        items=products,
        cursor=None,
        has_more=False,
        total=len(products),
    )
