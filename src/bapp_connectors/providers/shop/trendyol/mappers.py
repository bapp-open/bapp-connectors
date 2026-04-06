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
    FinancialTransaction,
    FinancialTransactionType,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    PaymentType,
    Product,
    ProviderMeta,
    WebhookEvent,
    WebhookEventType,
)

# ── Status mappings ──

TRENDYOL_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "Created": OrderStatus.PENDING,
    "Awaiting": OrderStatus.PENDING,
    "Picking": OrderStatus.PROCESSING,
    "Invoiced": OrderStatus.PROCESSING,
    "Shipped": OrderStatus.SHIPPED,
    "AtCollectionPoint": OrderStatus.SHIPPED,
    "Delivered": OrderStatus.DELIVERED,
    "Cancelled": OrderStatus.CANCELLED,
    "UnDelivered": OrderStatus.CANCELLED,
    "UnSupplied": OrderStatus.CANCELLED,
    "Returned": OrderStatus.RETURNED,
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


_MAPPED_LINE_KEYS = {
    "lineId",
    "productName",
    "stockCode",
    "merchantSku",
    "quantity",
    "lineUnitPrice",
    "vatRate",
    "discount",
}

_MAPPED_ORDER_KEYS = {
    "orderNumber",
    "shipmentPackageId",
    "status",
    "currencyCode",
    "customerEmail",
    "invoiceAddress",
    "shipmentAddress",
    "lines",
    "orderDate",
    "lastModifiedDate",
    "isCod",
    "grossAmount",
    "totalDiscount",
    "cargoTrackingNumber",
    "cargoTrackingLink",
    "cargoProviderName",
    "deliveryType",
}


def order_from_trendyol(data: dict) -> Order:
    """Map a Trendyol order response to a normalized Order DTO."""
    items = []
    for line in data.get("lines", []):
        items.append(
            OrderItem(
                item_id=str(line.get("lineId", line.get("id", ""))),
                product_id=line.get("stockCode", ""),
                sku=line.get("merchantSku") or line.get("stockCode", ""),
                name=line.get("productName", ""),
                quantity=Decimal(str(line.get("quantity", 1))),
                unit_price=Decimal(str(line.get("lineUnitPrice", 0))),
                currency=data.get("currencyCode", "TRY"),
                tax_rate=Decimal(str(line["vatRate"])) if line.get("vatRate") is not None else None,
                discount=Decimal(str(line["discount"])) if line.get("discount") else None,
                extra={k: v for k, v in line.items() if k not in _MAPPED_LINE_KEYS},
            )
        )

    order_date = None
    if ts := data.get("orderDate"):
        order_date = datetime.fromtimestamp(ts / 1000, tz=UTC)

    updated_at = None
    if ts := data.get("lastModifiedDate"):
        updated_at = datetime.fromtimestamp(ts / 1000, tz=UTC)

    raw_status = data.get("status", "")
    status = TRENDYOL_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    is_cod = data.get("isCod", False)
    payment_type = PaymentType.CASH_ON_DELIVERY if is_cod else PaymentType.ONLINE_CARD

    total = Decimal(str(data["grossAmount"])) if data.get("grossAmount") is not None else sum(
        item.unit_price * item.quantity for item in items
    )
    total_discount = Decimal(str(data["totalDiscount"])) if data.get("totalDiscount") else None

    return Order(
        order_id=str(data.get("orderNumber", "")),
        external_id=str(data.get("shipmentPackageId", "")) if data.get("shipmentPackageId") else None,
        status=status,
        raw_status=raw_status,
        payment_status=PaymentStatus.PAID if status != OrderStatus.PENDING else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency=data.get("currencyCode", "TRY"),
        items=items,
        billing=_map_contact(data.get("invoiceAddress"), data.get("customerEmail", "")),
        shipping=_map_contact(data.get("shipmentAddress"), data.get("customerEmail", "")),
        shipping_address=_map_address(data.get("shipmentAddress")),
        delivery_address=_format_delivery_address(data.get("shipmentAddress")),
        total=total,
        created_at=order_date,
        updated_at=updated_at,
        external_url=f"https://partner.trendyol.com/ro/orders/shipment-packages/all?orderNumber={data.get('orderNumber', '')}",
        provider_meta=ProviderMeta(
            provider="trendyol",
            raw_id=str(data.get("orderNumber", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            **({"total_discount": str(total_discount)} if total_discount else {}),
            **({"cargo_tracking_number": data["cargoTrackingNumber"]} if data.get("cargoTrackingNumber") else {}),
            **({"cargo_tracking_link": data["cargoTrackingLink"]} if data.get("cargoTrackingLink") else {}),
            **({"cargo_provider_name": data["cargoProviderName"]} if data.get("cargoProviderName") else {}),
            **({"delivery_type": data["deliveryType"]} if data.get("deliveryType") else {}),
            **{k: v for k, v in data.items() if k not in _MAPPED_ORDER_KEYS},
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


# ── Finance mappers ──


def _ms_to_datetime(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1000, tz=UTC)


TRENDYOL_TRANSACTION_TYPE_MAP: dict[str, FinancialTransactionType] = {
    "Sale": FinancialTransactionType.SALE,
    "Return": FinancialTransactionType.RETURN,
    "PaymentOrder": FinancialTransactionType.PAYMENT,
    "DeductionInvoices": FinancialTransactionType.DEDUCTION,
    "CreditNote": FinancialTransactionType.CREDIT_NOTE,
    "CommissionInvocie": FinancialTransactionType.COMMISSION,
}


def settlement_from_trendyol(data: dict, query_type: str = "") -> FinancialTransaction:
    """Map a Trendyol financial transaction to a normalized FinancialTransaction."""
    raw_type = data.get("transactionType", query_type)
    tx_type = TRENDYOL_TRANSACTION_TYPE_MAP.get(query_type, FinancialTransactionType.OTHER)
    debt = Decimal(str(data["debt"])) if data.get("debt") is not None else Decimal("0")
    credit = Decimal(str(data["credit"])) if data.get("credit") is not None else Decimal("0")

    return FinancialTransaction(
        transaction_id=data.get("id", ""),
        transaction_type=tx_type,
        raw_transaction_type=raw_type,
        transaction_date=_ms_to_datetime(data.get("transactionDate")),
        description=data.get("description") or "",
        debit=debt,
        credit=credit,
        net_amount=credit - debt,
        commission_rate=Decimal(str(data["commissionRate"])) if data.get("commissionRate") is not None else None,
        commission_amount=Decimal(str(data["commissionAmount"])) if data.get("commissionAmount") is not None else None,
        order_id=str(data.get("orderNumber", "")) if data.get("orderNumber") else "",
        invoice_number=data.get("commissionInvoiceSerialNumber") or "",
        payment_date=_ms_to_datetime(data.get("paymentDate")),
        provider_meta=ProviderMeta(
            provider="trendyol",
            raw_id=data.get("id", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in {
                "barcode": data.get("barcode"),
                "receipt_id": data.get("receiptId"),
                "payment_period": data.get("paymentPeriod"),
                "seller_revenue": str(data["sellerRevenue"]) if data.get("sellerRevenue") is not None else None,
                "payment_order_id": data.get("paymentOrderId"),
                "shipment_package_id": data.get("shipmentPackageId"),
                "store_name": data.get("storeName"),
                "country": data.get("country"),
                "affiliate": data.get("affiliate"),
            }.items()
            if v is not None
        },
    )


def settlements_from_trendyol(response: dict, query_type: str = "") -> PaginatedResult[FinancialTransaction]:
    """Map a paginated Trendyol settlements/financials response."""
    content = response.get("content", [])
    items = [settlement_from_trendyol(t, query_type=query_type) for t in content]
    total_pages = response.get("totalPages", 1)
    page = response.get("page", 0)
    return PaginatedResult(
        items=items,
        cursor=str(page + 1) if page + 1 < total_pages else None,
        has_more=page + 1 < total_pages,
        total=response.get("totalElements"),
    )


# ── Webhook mappers ──

TRENDYOL_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "CREATED": WebhookEventType.ORDER_CREATED,
    "PICKING": WebhookEventType.ORDER_UPDATED,
    "INVOICED": WebhookEventType.ORDER_UPDATED,
    "SHIPPED": WebhookEventType.ORDER_SHIPPED,
    "CANCELLED": WebhookEventType.ORDER_CANCELLED,
    "DELIVERED": WebhookEventType.ORDER_DELIVERED,
    "UNDELIVERED": WebhookEventType.ORDER_CANCELLED,
    "RETURNED": WebhookEventType.ORDER_CANCELLED,
    "UNSUPPLIED": WebhookEventType.ORDER_CANCELLED,
    "AWAITING": WebhookEventType.ORDER_UPDATED,
    "UNPACKED": WebhookEventType.ORDER_UPDATED,
    "AT_COLLECTION_POINT": WebhookEventType.ORDER_UPDATED,
    "VERIFIED": WebhookEventType.ORDER_UPDATED,
}


def webhook_event_from_trendyol(payload: dict) -> WebhookEvent:
    """Map a Trendyol webhook callback to a normalized WebhookEvent."""
    status = payload.get("status", "")
    event_type = TRENDYOL_WEBHOOK_EVENT_MAP.get(status, WebhookEventType.UNKNOWN)

    order_number = str(payload.get("orderNumber", ""))
    shipment_id = str(payload.get("shipmentPackageId", ""))
    event_id = shipment_id or order_number

    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="trendyol",
        provider_event_type=status,
        payload=payload,
        idempotency_key=f"trendyol:{status}:{event_id}" if event_id else "",
        received_at=datetime.now(UTC),
    )
