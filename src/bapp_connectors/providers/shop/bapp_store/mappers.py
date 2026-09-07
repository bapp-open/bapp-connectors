"""
Company Store <-> DTO mappers.

Outbound records follow the CatalogSyncTask contract (fixtures/products_batch.json);
inbound rows come from the store's public content-type viewsets.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from html.parser import HTMLParser

from bapp_connectors.core.dto import (
    Address,
    BulkItemResult,
    BulkUpsertResult,
    Contact,
    CustomerPricing,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    PaymentType,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductUpdate,
    ProviderMeta,
    ShopRules,
)
from bapp_connectors.core.pricing import to_gross, to_net
from bapp_connectors.providers.shop.bapp_store.models import SyncItemResult, SyncTaskResponse

DEFAULT_VAT_RATE = Decimal("0.21")

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip markup to plain text; block elements become line breaks."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    return "\n".join(line for line in lines if line)


def _price_amount(net_price: Decimal | None, bapp: dict, vat_rate: Decimal) -> str | None:
    if bapp.get("gross_price") is not None:
        return str(bapp["gross_price"])
    if net_price is None:
        return None
    return str(to_gross(net_price, vat_rate))


def _tiers(extra: dict) -> list[dict]:
    return [{"min_quantity": str(t["min_quantity"]), "price_amount": str(t["price"])} for t in extra.get("price_tiers", [])]


def _photos(photos: list[ProductPhoto]) -> list[dict]:
    return [{"url": p.url, "order": p.position} for p in photos]


def product_to_record(product: Product, vat_rate: Decimal = DEFAULT_VAT_RATE) -> dict:
    """Map a Product DTO to one CatalogSyncTask product record (create or full replace)."""
    bapp = dict(product.extra.get("bapp") or {})
    record: dict = {
        "id": product.product_id,
        "name": product.name,
        "code": product.sku or "",
        "code_ean": product.barcode or "",
        "unit": bapp.get("unit", "buc"),
        "description": html_to_text(product.description),
        "stock": str(product.stock if product.stock is not None else 0),
        "is_active": product.active,
        "category_ids": list(product.category_ids),
        "primary_category": product.category_ids[0] if product.category_ids else None,
        "price_tiers": _tiers(product.extra),
        "extra": {"bapp": bapp} if bapp else {},
    }
    amount = _price_amount(product.price, bapp, vat_rate)
    if amount is not None:
        record["price"] = {"amount": amount, "currency": product.currency or "RON"}
    if product.photos:
        record["photos"] = _photos(product.photos)
    return record


def update_to_record(update: ProductUpdate, vat_rate: Decimal = DEFAULT_VAT_RATE) -> dict:
    """Map a ProductUpdate to a partial record; absent keys keep their store values."""
    bapp = dict(update.extra.get("bapp") or {})
    record: dict = {"id": update.product_id}
    if update.name is not None:
        record["name"] = update.name
    if update.sku is not None:
        record["code"] = update.sku
    if update.barcode is not None:
        record["code_ean"] = update.barcode
    if update.description is not None:
        record["description"] = html_to_text(update.description)
    amount = _price_amount(update.price, bapp, vat_rate)
    if amount is not None:
        record["price"] = {"amount": amount, "currency": update.currency or "RON"}
    if update.stock is not None:
        record["stock"] = str(update.stock)
    if update.active is not None:
        record["is_active"] = update.active
    if update.category_ids is not None:
        record["category_ids"] = list(update.category_ids)
        record["primary_category"] = update.category_ids[0] if update.category_ids else None
    if update.photos is not None:
        record["photos"] = _photos(update.photos)
    if "price_tiers" in update.extra:
        record["price_tiers"] = _tiers(update.extra)
    if bapp:
        record["extra"] = {"bapp": bapp}
        if "unit" in bapp:
            record["unit"] = bapp["unit"]
    return record


def category_record(name: str, parent_id: str | None, local_id: str, is_active: bool | None = True) -> dict:
    """One CatalogSyncTask category record keyed by the BAPP category id."""
    record: dict = {"id": local_id, "parent_id": parent_id, "name": name}
    # None omits the key: an update carries name and parent only, so a store-side toggle survives it.
    if is_active is not None:
        record["is_active"] = is_active
    return record


def rules_to_body(rules: ShopRules) -> dict:
    """CatalogSyncTask `rules{}` body; the hash covers only the pricing inputs the store re-checks."""
    core = {
        "order_value_tiers": [
            {"min_total": str(t.min_total), "discount_percent": str(t.discount_percent)} for t in rules.order_value_tiers
        ],
        "min_order_total": str(rules.min_order_total) if rules.min_order_total is not None else None,
        # inside the hash on purpose: it derives from rolling-basis tiers, which never show up in
        # order_value_tiers, so outside the hash it would never sync at all
        "max_rolling_order_percent": str(rules.max_rolling_order_percent),
    }
    policy_hash = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**core, "currency": rules.currency, **rules.extra, "policy_hash": policy_hash}


def _pct(value: Decimal) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def customers_to_body(records: list[CustomerPricing], full: bool) -> dict:
    """CatalogSyncTask `customers[]` body. Quantized, because the store hashes what it receives."""
    return {
        "customers": [
            {
                "customer_key": r.customer_key,
                "order_value_percent": _pct(r.order_value_percent),
                "product_percents": [{"sku": p.sku, "discount_percent": _pct(p.discount_percent)} for p in r.product_percents],
            }
            for r in records
        ],
        "customers_full": full,
    }


def _bulk_item(item: SyncItemResult, index: int, local_id: str) -> BulkItemResult:
    return BulkItemResult(index=index, remote_id=item.id or local_id, error=item.error, error_code=item.code)


def bulk_result_from_response(response: dict, n_creates: int, n_updates: int, create_ids: list[str], update_ids: list[str]) -> BulkUpsertResult:
    """Split the task's positional `products[]` back into creates (first n_creates) and updates."""
    parsed = SyncTaskResponse.model_validate(response)
    created: list[BulkItemResult] = []
    updated: list[BulkItemResult] = []
    for item in parsed.products:
        if item.index < n_creates:
            created.append(_bulk_item(item, item.index, create_ids[item.index]))
        elif item.index < n_creates + n_updates:
            offset = item.index - n_creates
            updated.append(_bulk_item(item, offset, update_ids[offset]))
    return BulkUpsertResult(created=created, updated=updated)


def _parent_ref(parent) -> str | None:
    if isinstance(parent, dict):
        return str(parent.get("external_id") or parent.get("id") or "") or None
    return str(parent) if parent else None


def category_from_store(row: dict) -> ProductCategory:
    """Store category row -> DTO keyed by the BAPP id the store holds in `external_id`."""
    return ProductCategory(
        category_id=str(row["external_id"]),
        name=row.get("name", ""),
        parent_id=_parent_ref(row.get("parent")),
        extra={"store_id": str(row["id"]), "is_active": bool(row.get("is_active", True))},
    )


def product_from_store(row: dict, vat_rate: Decimal) -> Product:
    """Store product row -> DTO with the framework's net price."""
    gross = Decimal(str(row.get("price_amount") or "0"))
    return Product(
        product_id=str(row["external_id"]),
        sku=row.get("code") or None,
        barcode=row.get("code_ean") or None,
        name=row.get("name", ""),
        description=row.get("description") or "",
        price=to_net(gross, vat_rate),
        currency=row.get("currency") or "RON",
        stock=int(Decimal(str(row.get("stock_qty") or "0"))),
        active=bool(row.get("is_active", True)),
        extra={"store_id": str(row["id"]), "gross_price": str(gross)},
    )


# -- Order mappers --

STORE_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    **{s.value: s for s in OrderStatus},
    "confirmed": OrderStatus.ACCEPTED,
    "completed": OrderStatus.DELIVERED,
    "canceled": OrderStatus.CANCELLED,
}

STORE_PAYMENT_STATUS_MAP: dict[str, PaymentStatus] = {s.value: s for s in PaymentStatus}

STORE_PAYMENT_TYPE_MAP: dict[str, PaymentType] = {
    **{t.value: t for t in PaymentType},
    "card": PaymentType.ONLINE_CARD,
    "cod": PaymentType.CASH_ON_DELIVERY,
    "transfer": PaymentType.BANK_TRANSFER,
}

_ORDER_TOP_LEVEL_KEYS = frozenset(
    {
        "number",
        "created_at",
        "updated_at",
        "status",
        "payment_status",
        "payment_type",
        "currency",
        "billing",
        "delivery_address",
        "items",
        "total",
        "extra",
    }
)

_LINE_KEYS = frozenset({"product_id", "sku", "name", "quantity", "unit_price", "currency", "extra"})


def _billing_from_store(data: dict | None) -> Contact | None:
    if not data:
        return None
    address = Address(
        street=data.get("address", ""),
        city=data.get("city", ""),
        region=data.get("county", ""),
        postal_code=data.get("postal_code", ""),
        country="RO",
    )
    return Contact(
        name=data.get("name", ""),
        company_name=data.get("company_name", ""),
        vat_id=data.get("vat_id", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        address=address,
        extra={"reg_com": data.get("reg_com", "")},
    )


def _line_from_store(line: dict, currency: str, vat_rate: Decimal) -> OrderItem:
    gross = str(line["unit_price"])
    extra = {k: v for k, v in line.items() if k not in _LINE_KEYS}
    extra.update(line.get("extra") or {})
    extra["gross_unit_price"] = gross
    return OrderItem(
        product_id=str(line.get("product_id", "")),
        sku=line.get("sku", ""),
        name=line.get("name", ""),
        quantity=Decimal(str(line.get("quantity", "1"))),
        unit_price=to_net(Decimal(gross), vat_rate),
        currency=line.get("currency") or currency,
        tax_rate=vat_rate,
        extra=extra,
    )


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def order_from_store(data: dict, vat_rate: Decimal) -> Order:
    """Map one store order. Order.items carry LIST prices, not what was charged; the volume-discounted
    total is on Order.total, and the actual per-unit price charged is item.extra["unit_tier"] (gross,
    unconverted). See the README's Orders section."""
    number = str(data["number"])
    currency = data.get("currency", "RON")
    raw_status = data.get("status", "")
    raw_payment_status = data.get("payment_status", "")
    raw_payment_type = data.get("payment_type", "")
    gross_total = str(data.get("total", "0"))

    extra = {k: v for k, v in data.items() if k not in _ORDER_TOP_LEVEL_KEYS}
    extra.update(data.get("extra") or {})
    extra["gross_total"] = gross_total
    extra["raw_payment_status"] = raw_payment_status
    extra["raw_payment_type"] = raw_payment_type

    return Order(
        order_id=number,
        external_id=number,
        status=STORE_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING),
        raw_status=raw_status,
        payment_status=STORE_PAYMENT_STATUS_MAP.get(raw_payment_status, PaymentStatus.UNPAID),
        payment_type=STORE_PAYMENT_TYPE_MAP.get(raw_payment_type, PaymentType.OTHER) if raw_payment_type else None,
        currency=currency,
        items=[_line_from_store(line, currency, vat_rate) for line in data.get("items", [])],
        billing=_billing_from_store(data.get("billing")),
        delivery_address=data.get("delivery_address", ""),
        total=to_net(Decimal(gross_total), vat_rate),
        created_at=_parse_iso(data.get("created_at")),
        updated_at=_parse_iso(data.get("updated_at")),
        external_url=(data.get("extra") or {}).get("order_url", ""),
        provider_meta=ProviderMeta(provider="bapp_store", raw_id=number, raw_payload=data, fetched_at=datetime.now(UTC)),
        extra=extra,
    )


def orders_page_from_store(data: dict, vat_rate: Decimal) -> PaginatedResult[Order]:
    return PaginatedResult(
        items=[order_from_store(row, vat_rate) for row in data.get("items", [])],
        cursor=data.get("cursor"),
        has_more=bool(data.get("has_more", False)),
    )
