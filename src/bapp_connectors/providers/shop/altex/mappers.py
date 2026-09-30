"""Altex Marketplace <-> DTO mappers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from bapp_connectors.core.dto import (
    Address,
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaymentStatus,
    PaymentType,
    Product,
)

# Order status codes (spec): 1 Registered, 2 In Progress, 3 Partial Shipped, 4 Shipped,
# 5 Partial Returned, 6 Returned, 7 Cancelled, 8 Ready to be shipped, 9 Completed,
# 10 Technical cancelling, 11 Cancelled - Refund accepted.
ALTEX_STATUS_MAP: dict[int, OrderStatus] = {
    1: OrderStatus.PENDING,
    2: OrderStatus.ACCEPTED,
    3: OrderStatus.PROCESSING,
    4: OrderStatus.SHIPPED,
    5: OrderStatus.DELIVERED,  # partially returned: the rest was delivered
    6: OrderStatus.RETURNED,
    7: OrderStatus.CANCELLED,
    8: OrderStatus.PROCESSING,
    9: OrderStatus.DELIVERED,
    10: OrderStatus.CANCELLED,
    11: OrderStatus.REFUNDED,
}

# What we may ask Altex to move an order to.
ALTEX_STATUS_CODES: dict[OrderStatus, int] = {
    OrderStatus.ACCEPTED: 2,
    OrderStatus.PROCESSING: 2,
    OrderStatus.SHIPPED: 4,
    OrderStatus.DELIVERED: 9,
    OrderStatus.CANCELLED: 7,
    OrderStatus.RETURNED: 6,
}

ALTEX_PAYMENT_MAP: dict[int, PaymentType] = {
    1: PaymentType.CASH_ON_DELIVERY,
    2: PaymentType.BANK_TRANSFER,
    3: PaymentType.ONLINE_CARD,
    4: PaymentType.OTHER,  # Credex (instalments)
}


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "")) if value not in (None, "") else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _int(value) -> int | None:
    try:
        return int(str(value).strip(" ,"))
    except (TypeError, ValueError):
        return None


def _dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _contact(data: dict, prefix: str) -> Contact:
    def get(key):
        return str(data.get(f"{prefix}_{key}") or "").strip()

    return Contact(
        name=get("customer_name"),
        company_name=get("company_name"),
        vat_id=get("company_code"),
        phone=get("phone_number"),
        address=Address(street=get("address"), city=get("city"), region=get("region"),
                        country=get("country") or "RO"),
        extra={"registration_number": get("company_registration_number"), "bank": get("company_bank"),
               "iban": get("company_iban")},
    )


def order_from_altex(data: dict) -> Order:
    status = _int(data.get("status"))
    payment_mode = _int(data.get("payment_mode"))
    items = [
        OrderItem(
            item_id=str(line.get("id") or ""),
            product_id=str(line.get("product_id") or ""),
            sku=str(line.get("seller_product_code") or ""),
            name=str(line.get("name") or ""),
            quantity=_dec(line.get("quantity") or 1),
            # the promo price when there is one; both include VAT
            unit_price=_dec(line.get("selling_price") or line.get("catalog_price")),
            currency="RON",
            tax_rate=_dec(line.get("vat")) if line.get("vat") not in (None, "") else None,
            extra={"catalog_price": line.get("catalog_price"), "row_total": line.get("row_total"),
                   "line_status": line.get("status"), "commission": line.get("commission"),
                   "offer_id": (line.get("aditional_data") or {}).get("offer_id"),  # sic, "aditional"
                   "external_id": line.get("external_id")},
        )
        for line in data.get("products") or []
    ]
    shipping = _contact(data, "shipping")
    return Order(
        order_id=str(data.get("order_code") or data.get("order_id") or ""),
        external_id=str(data.get("order_id") or ""),
        status=ALTEX_STATUS_MAP.get(status, OrderStatus.PENDING),
        raw_status=str(data.get("status") or ""),
        payment_status=PaymentStatus.PAID if payment_mode == 3 else PaymentStatus.UNPAID,
        payment_type=ALTEX_PAYMENT_MAP.get(payment_mode, PaymentType.OTHER),
        currency="RON",
        items=items,
        billing=_contact(data, "billing"),
        shipping=shipping,
        shipping_address=shipping.address,
        delivery_address=", ".join(filter(None, [str(data.get("delivery_address") or ""),
                                                 str(data.get("delivery_city") or "")])),
        total=_dec(data.get("total_price")),
        created_at=_dt(data.get("order_date")),
        extra={"shipping_tax": data.get("shipping_tax"), "payment_tax": data.get("payment_tax"),
               "products_price": data.get("products_price"), "delivery_mode": data.get("delivery_mode"),
               "altex_courier": _int(data.get("delivery_mode")) == 4,
               "gift_card_amount": data.get("gift_card_amount"), "awbs": data.get("awbs") or [],
               "invoices": data.get("invoices") or []},
    )


def product_from_offer(offer: dict) -> Product:
    stock = offer.get("stock")
    if isinstance(stock, list):
        quantity = sum(_int(s.get("quantity")) or 0 for s in stock if isinstance(s, dict))
    else:
        quantity = _int(stock)
    price = offer.get("selling_price") or offer.get("price")
    return Product(
        product_id=str(offer.get("id") or "").strip(" ,"),  # the offer id: price and stock go per offer
        sku=str(offer.get("seller_product_code") or "") or None,
        price=_dec(price) if price not in (None, "") else None,
        currency="RON",
        stock=quantity,
        active=_int(offer.get("status")) == 1,
        extra={"altex_product_id": offer.get("product_id"), "price": offer.get("price"),
               "min_selling_price": offer.get("min_selling_price"), "vat": offer.get("vat"),
               "pending_stock": offer.get("pending_stock"), "is_processed": offer.get("is_processed")},
    )
