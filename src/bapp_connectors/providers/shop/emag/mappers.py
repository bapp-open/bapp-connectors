"""
eMAG <-> DTO mappers.

Converts between raw eMAG API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    Address,
    Contact,
    FinancialInvoice,
    FinancialInvoiceLine,
    FinancialTransaction,
    FinancialTransactionType,
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
from bapp_connectors.core.dto.webhook import WebhookEvent, WebhookEventType
from bapp_connectors.providers.shop.emag.models import EmagApiResponse

if TYPE_CHECKING:
    from bapp_connectors.core.status_mapping import StatusMapper

# ── Status mappings (defaults — tenants can override via connection config) ──

# eMAG order statuses (numeric, stored as strings for StatusMapper compatibility):
# 0 = cancelled/storno, 1 = new, 2 = in progress, 3 = prepared, 4 = finalized, 5 = returned
EMAG_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "0": OrderStatus.CANCELLED,
    "1": OrderStatus.PENDING,
    "2": OrderStatus.ACCEPTED,
    "3": OrderStatus.SHIPPED,
    "4": OrderStatus.DELIVERED,
    "5": OrderStatus.RETURNED,
}

ORDER_STATUS_TO_EMAG: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "1",
    OrderStatus.ACCEPTED: "2",
    OrderStatus.PROCESSING: "2",
    OrderStatus.SHIPPED: "3",
    OrderStatus.DELIVERED: "4",
    OrderStatus.CANCELLED: "0",
    OrderStatus.RETURNED: "5",
    OrderStatus.REFUNDED: "5",
}

# eMAG payment modes by ID (numeric, most reliable) and by string name (fallback)
EMAG_PAYMENT_MODE_ID_MAP: dict[int, PaymentType] = {
    1: PaymentType.CASH_ON_DELIVERY,
    2: PaymentType.BANK_TRANSFER,
    3: PaymentType.ONLINE_CARD,
}

EMAG_PAYMENT_MODE_MAP: dict[str, PaymentType] = {
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

    # Extract legal_entity (0=individual, 1=company) from customer data
    legal_entity = customer.get("legal_entity", 0)

    return Contact(
        name=name,
        company_name=company,
        vat_id=addr.get("fiscal_code", "").strip() if addr.get("fiscal_code") else "",
        email=email,
        phone=phone,
        address=_map_address(addr, country),
        extra={"legal_entity": legal_entity} if legal_entity else {},
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


def order_from_emag(data: dict, country: str = "RO", *, status_mapper: StatusMapper | None = None) -> Order:
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

    # Shipping tax as a separate line item (for accurate invoicing)
    shipping_tax = data.get("shipping_tax")
    if shipping_tax is not None:
        shipping_amount = Decimal(str(shipping_tax))
        if shipping_amount > 0:
            items.append(
                OrderItem(
                    item_id="shipping",
                    product_id="SHIPPING",
                    name="Transport",
                    quantity=Decimal("1"),
                    unit_price=shipping_amount,
                    currency=data.get("products", [{}])[0].get("currency", "RON") if data.get("products") else "RON",
                    extra={"is_transport": True},
                )
            )

    # Voucher line items (negative amounts for discounts)
    for voucher in data.get("vouchers", []):
        voucher_value = Decimal(str(voucher.get("sale_price", voucher.get("value", 0))))
        if voucher_value:
            items.append(
                OrderItem(
                    item_id=str(voucher.get("id", "voucher")),
                    product_id=voucher.get("voucher_name", voucher.get("name", "VOUCHER")),
                    name=voucher.get("voucher_name", voucher.get("name", "Voucher")),
                    quantity=Decimal("1"),
                    unit_price=-abs(voucher_value),
                    currency=data.get("products", [{}])[0].get("currency", "RON") if data.get("products") else "RON",
                    extra={"is_voucher": True, **{k: v for k, v in voucher.items() if k not in ("id", "sale_price", "value", "voucher_name", "name")}},
                )
            )

    order_date = None
    if date_str := data.get("date"):
        with contextlib.suppress(ValueError, TypeError):
            order_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    raw_status = str(data.get("status", 1))
    if status_mapper:
        status = status_mapper.to_framework(raw_status)
    else:
        status = EMAG_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    # Payment type: prefer numeric payment_mode_id, fall back to string payment_mode
    payment_mode_id = data.get("payment_mode_id")
    if payment_mode_id is not None:
        payment_type = EMAG_PAYMENT_MODE_ID_MAP.get(int(payment_mode_id), PaymentType.OTHER)
    else:
        payment_mode = data.get("payment_mode", "").lower().strip()
        payment_type = EMAG_PAYMENT_MODE_MAP.get(payment_mode, PaymentType.OTHER)

    # Payment status: eMAG payment_status field (0=unpaid, 1=paid)
    raw_payment_status = data.get("payment_status", 0)
    payment_status = PaymentStatus.PAID if raw_payment_status == 1 else PaymentStatus.UNPAID

    # Calculate total from all line items (products + shipping + vouchers)
    total = sum(item.unit_price * item.quantity for item in items)

    # Determine currency from items or default
    currency = items[0].currency if items else "RON"

    # HUF rounding — Hungarian marketplace uses whole numbers
    if currency == "HUF":
        total = total.quantize(Decimal("1"))
        items = [
            OrderItem(
                item_id=item.item_id,
                product_id=item.product_id,
                sku=item.sku,
                name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price.quantize(Decimal("1")),
                currency=item.currency,
                tax_rate=item.tax_rate,
                extra=item.extra,
            )
            for item in items
        ]

    emag_id = str(data.get("id", ""))

    return Order(
        order_id=emag_id,
        external_id=emag_id,
        status=status,
        raw_status=raw_status,
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
                "vouchers",
            )
        },
    )


def orders_from_emag(
    response: EmagApiResponse, country: str = "RO", *, status_mapper: StatusMapper | None = None
) -> PaginatedResult[Order]:
    """Map a paginated eMAG orders response to PaginatedResult[Order]."""
    orders = [order_from_emag(o, country, status_mapper=status_mapper) for o in response.results]
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

    # Parse validation_status for is_public / is_public_reason
    is_public = False
    is_public_reason = ""
    for vs in data.get("validation_status", []):
        if vs.get("value") == 9:
            is_public = True
        elif vs.get("description"):
            is_public_reason = vs["description"]

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
            "is_public": is_public,
            "is_public_reason": is_public_reason,
            **{
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
                    "validation_status",
                )
            },
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


# ── Webhook event mapper ──

EMAG_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "order.created": WebhookEventType.ORDER_CREATED,
    "order.cancel": WebhookEventType.ORDER_CANCELLED,
    "awb.update": WebhookEventType.SHIPMENT_IN_TRANSIT,
    "return.created": WebhookEventType.ORDER_CANCELLED,
    "product.created": WebhookEventType.PRODUCT_CREATED,
    "product.approved": WebhookEventType.PRODUCT_UPDATED,
}


def webhook_event_from_emag(event_code: str, payload: dict) -> WebhookEvent:
    """Map an eMAG IPN callback to a normalized WebhookEvent."""
    event_type = EMAG_WEBHOOK_EVENT_MAP.get(event_code, WebhookEventType.UNKNOWN)

    # Extract a meaningful ID for deduplication
    event_id = ""
    if "id" in payload:
        event_id = str(payload["id"])
    elif "order_id" in payload:
        event_id = str(payload["order_id"])

    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="emag",
        provider_event_type=event_code,
        payload=payload,
        idempotency_key=f"emag:{event_code}:{event_id}" if event_id else "",
        received_at=datetime.now(UTC),
    )


# ── Invoice / Financial mappers ──


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    with contextlib.suppress(ValueError):
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    return None


def _map_invoice_lines(lines: list[dict]) -> list[FinancialInvoiceLine]:
    result = []
    for line in lines:
        unit_price = Decimal(str(line.get("unit_price", 0)))
        quantity = Decimal(str(line.get("quantity", 1)))
        result.append(
            FinancialInvoiceLine(
                description=line.get("product_name", ""),
                quantity=quantity,
                unit_price=unit_price,
                vat_rate=Decimal(str(line.get("vat_rate", 0))),
                amount=Decimal(str(line.get("value", 0))) if line.get("value") else unit_price * quantity,
                unit_of_measure=line.get("unit_of_measure", ""),
            )
        )
    return result


def invoice_from_emag(data: dict) -> FinancialInvoice:
    """Map an eMAG invoice response to a normalized FinancialInvoice."""
    supplier = data.get("supplier", {})
    customer = data.get("customer", {})
    lines = _map_invoice_lines(data.get("lines", []))

    # Use pre-calculated totals from eMAG when available
    total_amount = Decimal(str(data["total_without_vat"])) if data.get("total_without_vat") is not None else sum(
        line.amount for line in lines
    )
    total_vat = Decimal(str(data["total_vat_value"])) if data.get("total_vat_value") is not None else Decimal("0")

    return FinancialInvoice(
        invoice_number=data.get("number", ""),
        category=data.get("category", ""),
        date=_parse_date(data.get("date")),
        is_storno=bool(data.get("is_storno")),
        reversal_for=data.get("reversal_for", ""),
        currency=data.get("currency", ""),
        supplier_name=supplier.get("name", ""),
        supplier_tax_id=supplier.get("cif", ""),
        customer_name=customer.get("name", ""),
        customer_tax_id=customer.get("cif", ""),
        total_amount=total_amount,
        total_vat=total_vat,
        lines=lines,
        order_id=str(data.get("order_id", "")) if data.get("order_id") else "",
        provider_meta=ProviderMeta(
            provider="emag",
            raw_id=data.get("number", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


def invoices_from_emag(response: dict) -> PaginatedResult[FinancialInvoice]:
    """Map eMAG invoice response to PaginatedResult.

    Invoice endpoints return {isError, results: {total_results, invoices}}.
    """
    results = response.get("results", response)
    if isinstance(results, dict):
        invoice_list = results.get("invoices", [])
        total = results.get("total_results", len(invoice_list))
    else:
        invoice_list = results
        total = len(invoice_list)

    invoices = [invoice_from_emag(inv) for inv in invoice_list]
    return PaginatedResult(
        items=invoices,
        has_more=len(invoices) > 0 and len(invoices) >= 100,
        total=total,
    )


EMAG_INVOICE_CATEGORY_TRANSACTION_TYPE: dict[str, FinancialTransactionType] = {
    "FC": FinancialTransactionType.COMMISSION,
    "FP": FinancialTransactionType.PAYMENT,
}


def transactions_from_emag_invoices(response: dict) -> PaginatedResult[FinancialTransaction]:
    """Convert eMAG invoices to normalized FinancialTransactions."""
    invoice_result = invoices_from_emag(response)
    transactions = []
    for inv in invoice_result.items:
        tx_type = EMAG_INVOICE_CATEGORY_TRANSACTION_TYPE.get(inv.category, FinancialTransactionType.OTHER)
        net = inv.total_amount + inv.total_vat
        transactions.append(
            FinancialTransaction(
                transaction_id=inv.invoice_number,
                transaction_type=tx_type,
                raw_transaction_type=inv.category,
                transaction_date=inv.date,
                description=f"{inv.category} - {inv.invoice_number}",
                debit=net if net > 0 else Decimal("0"),
                credit=abs(net) if net < 0 else Decimal("0"),
                net_amount=net,
                order_id=inv.order_id,
                invoice_number=inv.invoice_number,
                provider_meta=inv.provider_meta,
            )
        )
    return PaginatedResult(
        items=transactions,
        has_more=invoice_result.has_more,
        total=invoice_result.total,
    )
