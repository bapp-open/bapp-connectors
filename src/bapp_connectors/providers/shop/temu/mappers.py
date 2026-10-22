"""Temu payloads → framework DTOs. No network, no state."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import Address, Contact, Order, OrderItem, Product, ProductPhoto, ProductVariant, ProviderMeta
from bapp_connectors.core.dto.order import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.core.errors import ValidationError
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


# ──────────────────────────────────────────────────────────────────── products

def _money(value: Decimal | None, currency: str) -> dict:
    return {"amount": f"{(value or Decimal('0')).quantize(Decimal('0.01'))}", "currency": currency}


def _package_info(extra: dict, cfg: dict) -> dict:
    package = (extra or {}).get("package") or {}

    def pick(key: str, default_key: str) -> str:
        value = package.get(key)
        try:
            number = Decimal(str(value)) if value is not None else Decimal("0")
        except (ArithmeticError, ValueError):
            number = Decimal("0")
        if number <= 0:
            number = Decimal(str(cfg.get(default_key) or 0))
        text = f"{number.normalize():f}"
        return text if text else "0"

    return {
        "weight": pick("weight_g", "default_weight_g"),
        "length": pick("length_cm", "default_length_cm"),
        "width": pick("width_cm", "default_width_cm"),
        "height": pick("height_cm", "default_height_cm"),
    }


def _sku_entry(external_sku_id: str, images: list[str], price: Decimal | None, currency: str, quantity: int | None,
               variations: list[dict], barcode: str | None, extra: dict, cfg: dict) -> dict:
    if not external_sku_id:
        raise ValidationError("Temu cere un cod (SKU) pentru fiecare produs/variantă")
    if not images:
        raise ValidationError("Temu cere cel puțin o imagine (URL public) per SKU")
    entry = {
        "externalSkuId": external_sku_id[:128],
        "images": images[:10],
        "price": {"basePrice": _money(price, currency)},
        "quantity": int(quantity or 0),
        "packageInfo": _package_info(extra, cfg),
        "variations": variations or [{"name": "Color", "value": "as shown"}],
    }
    if barcode:
        entry["barCode"] = {"barCodeType": "EAN", "barCodeId": [barcode]}
    return entry


def goods_v3_payload(product: Product, cfg: dict) -> dict:
    """Product DTO → ``temu.local.goods.v3.add`` body (without the common parameters)."""
    currency = product.currency or str(cfg.get("currency") or "RON")
    photos = [p.url for p in product.photos if p.url]
    basic: dict = {
        "externalGoodsId": (product.sku or "")[:128],
        "goodsName": product.name[:500],
        "productType": 1,
    }
    if not basic["externalGoodsId"]:
        raise ValidationError("Temu cere un cod (SKU) pentru produs")
    if product.description:
        basic["goodsDesc"] = product.description[:10000]
    if product.categories:
        basic["extCatName"] = " / ".join(c for c in product.categories if c)[:500]
    if photos:
        basic["goodsCarouselImage"] = photos[:10]
        basic["detailImage"] = photos[:50]
    limit_day = cfg.get("shipment_limit_day")
    if limit_day not in (None, "", 0):
        basic["shipmentLimitDay"] = int(limit_day)

    attributes = [
        {"name": a.attribute_name[:128], "value": [str(v)[:128] for v in a.values][:1000]}
        for a in product.attributes if a.attribute_name and a.values and not a.used_for_variants
    ][:200]
    brand = (product.extra or {}).get("brand")
    if brand:
        attributes.append({"name": "Brand", "value": [str(brand)[:128]]})

    if product.variants:
        sku_list = [
            _sku_entry(
                v.sku or "", [v.image_url] if v.image_url else photos, v.price if v.price is not None else product.price,
                currency, v.stock if v.stock is not None else product.stock,
                [{"name": str(k)[:128], "value": str(val)[:128]} for k, val in (v.attributes or {}).items()][:5],
                v.barcode, {**(product.extra or {}), **(v.extra or {})}, cfg,
            )
            for v in product.variants
        ]
    else:
        sku_list = [_sku_entry(product.sku or "", photos, product.price, currency, product.stock, [], product.barcode,
                               product.extra or {}, cfg)]

    payload = {"goodsBasic": basic, "skuList": sku_list[:500]}
    if attributes:
        payload["attributes"] = attributes
    return payload


def product_from_goods(item: dict) -> Product:
    """One row of ``bg.local.goods.list.query`` → Product DTO."""
    skus = item.get("skuInfoList") or []
    variants = []
    for sku in skus:
        specs = {str(s.get("parentSpecName") or ""): str(s.get("specName") or "") for s in (sku.get("specList") or [])}
        variants.append(ProductVariant(
            variant_id=str(sku.get("skuId") or ""),
            sku=sku.get("skuSn") or sku.get("outSkuSn") or None,
            stock=int(sku.get("stock") or 0) if sku.get("stock") is not None else None,
            attributes={k: v for k, v in specs.items() if k},
            extra={k: v for k, v in sku.items() if k not in ("specList",)},
        ))
    stocks = [v.stock for v in variants if v.stock is not None]
    price = None
    for key in ("price", "retailPrice", "listPrice"):
        raw = item.get(key)
        if raw not in (None, "", 0, "0", "0.0"):
            try:
                price = Decimal(str(raw))
                break
            except ArithmeticError:
                continue
    photos = [ProductPhoto(url=item["thumbUrl"], position=0)] if item.get("thumbUrl") else []
    return Product(
        product_id=str(item.get("goodsId") or ""),
        sku=item.get("outGoodsSn") or None,
        name=str(item.get("goodsName") or ""),
        price=price,
        currency=str(item.get("currency") or ""),
        stock=sum(stocks) if stocks else None,
        active=item.get("goodsShowSubStatus") not in (None, 0) if "goodsShowSubStatus" in item else True,
        photos=photos,
        variants=variants,
        extra={k: item.get(k) for k in ("goodsStatus", "goodsShowSubStatus", "status4VO", "subStatus4VO", "catId",
                                         "crtTime", "goodsStatusChangeTime", "outSkuSnList", "skuIdList") if k in item},
        provider_meta=ProviderMeta(provider="temu", raw_id=str(item.get("goodsId") or ""), raw_payload=item),
    )


def sku_ids_from_stock_query(data: dict) -> list[tuple[int, str]]:
    """``temu.local.goods.sku.stock.query`` → [(skuId, outSkuSn), …] across all goods in the answer."""
    pairs: list[tuple[int, str]] = []
    for goods in (data or {}).get("stockList") or []:
        for sku in goods.get("skuStockInfoList") or []:
            if sku.get("skuId") is not None:
                pairs.append((int(sku["skuId"]), str(sku.get("outSkuSn") or "")))
    for sku in (data or {}).get("skuStockList") or []:  # tolerated alternative shape
        if sku.get("skuId") is not None:
            pairs.append((int(sku["skuId"]), str(sku.get("skuSn") or sku.get("outSkuSn") or "")))
    return pairs
