"""Temu payloads → framework DTOs. No network, no state."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import Address, Contact, Order, OrderItem, ProviderMeta
from bapp_connectors.core.dto.order import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.providers.shop.temu.models import REGION_COUNTRY, ParentOrderStatus

if TYPE_CHECKING:
    from bapp_connectors.core.capabilities import OrderAmounts

PARENT_STATUS_MAP = {
    ParentOrderStatus.PENDING: OrderStatus.PENDING,
    ParentOrderStatus.UNSHIPPED: OrderStatus.PROCESSING,
    ParentOrderStatus.CANCELLED: OrderStatus.CANCELLED,
    ParentOrderStatus.SHIPPED: OrderStatus.SHIPPED,
    ParentOrderStatus.RECEIVED: OrderStatus.DELIVERED,
}


def _ts(value) -> datetime.datetime | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)


def country_from_region(name: str | None) -> str:
    return REGION_COUNTRY.get((name or "").strip().lower(), "")


def contact_from_shipping_info(data: dict) -> Contact:
    """``bg.order.shippinginfo.v2.get`` / ``decryptshippinginfo`` → Contact.

    The e-mail Temu gives is a relay address, not the buyer's: it stays out of ``email`` and
    rides in ``extra["relay_email"]`` so the host never matches a partner on it.
    """
    data = data or {}
    street = (data.get("addressLineAll") or data.get("addressLine1") or "").strip()
    extra_line = (data.get("addressLine2") or "").strip()
    if extra_line and extra_line not in street and not data.get("addressLineAll"):
        street = f"{street}, {extra_line}"
    return Contact(
        name=(data.get("receiptName") or "").strip(),
        phone=(data.get("mobile") or "").strip(),
        email="",
        address=Address(
            street=street,
            city=(data.get("regionName2") or "").strip(),
            region=(data.get("regionName3") or "").strip(),
            postal_code=(data.get("postCode") or "").strip(),
            country=country_from_region(data.get("regionName1")),
        ),
        extra={"relay_email": data.get("mail") or "", "backup_mobile": data.get("backupMobile") or ""},
    )


def _item_from_order_line(line: dict, currency: str, amounts: OrderAmounts | None) -> OrderItem:
    order_sn = str(line.get("orderSn") or "")
    products = line.get("productList") or []
    sku = str((products[0] or {}).get("extCode") or "") if products else ""
    packages = line.get("packageSnInfo") or []
    unit_price = Decimal("0")
    tax_rate = None
    if amounts is not None:
        for amount_line in amounts.lines:
            if amount_line.item_id == order_sn:
                unit_price = amount_line.unit_price_incl_vat
                tax_rate = amount_line.vat_rate
                break
    return OrderItem(
        item_id=order_sn,
        product_id=str(line.get("goodsId") or ""),
        sku=sku,
        name=str(line.get("goodsName") or line.get("originalGoodsName") or ""),
        quantity=Decimal(str(line.get("quantity") or 1)),
        unit_price=unit_price,
        currency=currency,
        tax_rate=tax_rate,
        extra={
            "skuId": line.get("skuId"),
            "productSkuId": (products[0] or {}).get("productSkuId") if products else None,
            "spec": line.get("spec") or "",
            "fulfillmentType": line.get("fulfillmentType") or "",
            "packageSn": str((packages[0] or {}).get("packageSn") or "") if packages else "",
            "canceledQuantityBeforeShipment": line.get("canceledQuantityBeforeShipment") or 0,
            "orderStatus": line.get("orderStatus"),
        },
    )


def order_from_temu(parent: dict, shipping: dict | None, site_currency: str, amounts: OrderAmounts | None = None) -> Order:
    """One Temu parent order (``bg.order.list.v2.get`` row or ``bg.order.detail.v2.get``) → Order."""
    head = parent.get("parentOrderMap") or {}
    lines = parent.get("orderList") or []
    parent_sn = str(head.get("parentOrderSn") or "")
    raw_status = head.get("parentOrderStatus")
    try:
        status = PARENT_STATUS_MAP.get(ParentOrderStatus(int(raw_status)), OrderStatus.PENDING)
    except (TypeError, ValueError):
        status = OrderStatus.PENDING
    items = [_item_from_order_line(line, site_currency, amounts) for line in lines]
    contact = contact_from_shipping_info(shipping) if shipping else None
    extra = {
        "site_id": head.get("siteId"),
        "region_id": head.get("regionId"),
        "relay_email": (contact.extra.get("relay_email") if contact else "") or "",
        "amounts_missing": amounts is None,
        "parent_order_time": head.get("parentOrderTime"),
        "expect_ship_latest_time": head.get("expectShipLatestTime"),
        "parent_shipping_time": head.get("parentShippingTime"),
        "fulfillment_type": str((lines[0] or {}).get("fulfillmentType") or "") if lines else "",
        "order_payment_type": head.get("orderPaymentType") or "",
        "shipping_method": head.get("shippingMethod"),
    }
    if amounts is not None:
        extra["amounts"] = {
            "customer_paid_total": str(amounts.customer_paid_total),
            "estimated_revenue": str(amounts.estimated_revenue),
            "estimated_revenue_deduction": str(amounts.estimated_revenue_deduction),
            "source": amounts.source,
        }
    return Order(
        order_id=parent_sn,
        external_id=parent_sn,
        status=status,
        raw_status=str(raw_status if raw_status is not None else ""),
        payment_status=PaymentStatus.PAID,
        payment_type=PaymentType.ONLINE_CARD,
        currency=site_currency,
        items=items,
        billing=contact,
        shipping=contact,
        shipping_address=contact.address if contact else None,
        total=amounts.customer_paid_total if amounts is not None else Decimal("0"),
        created_at=_ts(head.get("parentOrderTime")),
        updated_at=_ts(head.get("updateTime")) or _ts(head.get("parentOrderTime")),
        extra=extra,
        provider_meta=ProviderMeta(provider="temu", raw_id=parent_sn, raw_payload=parent),
    )
