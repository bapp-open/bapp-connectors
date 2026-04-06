"""
Gomag <-> DTO mappers.

Converts between raw Gomag API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.

IMPORTANT: The Gomag API returns products as a dict keyed by product ID,
not as a list. The normalization to list happens here.

Multilingual:
    Gomag write endpoints accept names/descriptions as ``{"ro": "...", "en": "..."}``.
    Read endpoints return a plain string (for the store's default language) unless
    ``view=<lang>`` is passed.  DTOs are single-language; the ``lang`` parameter on
    outbound helpers controls which language key is used when writing.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    Address,
    AttributeDefinition,
    AttributeValue,
    AWBLabel,
    BulkResult,
    Contact,
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
)

if TYPE_CHECKING:
    from bapp_connectors.core.status_mapping import StatusMapper

DEFAULT_LANG = "ro"

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
    billing = data.get("billing", {})
    first = data.get("payment_firstname") or billing.get("firstname", data.get("firstname", ""))
    last = data.get("payment_lastname") or billing.get("lastname", data.get("lastname", ""))
    name = f"{first} {last}".strip()
    if not name:
        return None
    company = billing.get("company", {})
    company_name = company.get("name", "") if isinstance(company, dict) else data.get("payment_company", data.get("company", ""))
    return Contact(
        name=name,
        company_name=str(company_name).strip(),
        vat_id=company.get("code", "").strip() if isinstance(company, dict) else "",
        email=(billing.get("email") or data.get("email", "")).lower().strip(),
        phone=(billing.get("phone") or data.get("telephone", "")).strip(),
        address=_map_billing_address(data),
    )


def _map_shipping_contact(data: dict) -> Contact | None:
    shipping = data.get("shipping", {})
    first = data.get("shipping_firstname") or shipping.get("firstname", "")
    last = data.get("shipping_lastname") or shipping.get("lastname", "")
    name = f"{first} {last}".strip()
    if not name:
        return None
    return Contact(
        name=name,
        company_name=(shipping.get("company") or data.get("shipping_company", "")).strip(),
        email=(shipping.get("email") or data.get("email", "")).lower().strip(),
        phone=(shipping.get("phone") or data.get("telephone", "")).strip(),
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
    raw_items = data.get("products") or data.get("items") or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    for line in raw_items:
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
    date_str = data.get("date_added") or data.get("date")
    if date_str:
        try:
            order_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            with contextlib.suppress(ValueError, AttributeError):
                order_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    raw_status = data.get("status_name", data.get("status", ""))
    if status_mapper:
        status = status_mapper.to_framework(raw_status)
    else:
        status = GOMAG_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)

    payment_method = data.get("payment_method", "")
    if isinstance(data.get("payment"), dict):
        payment_method = payment_method or data["payment"].get("name", "")
    payment_type = GOMAG_PAYMENT_METHOD_MAP.get(payment_method, PaymentType.OTHER)

    total = Decimal(str(data.get("total", 0)))
    order_id = str(data.get("order_id") or data.get("number") or data.get("id", ""))

    return Order(
        order_id=order_id,
        external_id=str(data.get("id", "")) if data.get("id") else None,
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
            raw_id=order_id,
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
    raw_orders = _normalize_gomag_list(response, key="orders")
    orders = [order_from_gomag(o, status_mapper=status_mapper) for o in raw_orders]
    has_more = len(raw_orders) > 0 and len(raw_orders) >= 100
    return PaginatedResult(
        items=orders,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


def order_to_gomag(order: Order) -> dict:
    """Map an Order DTO to a Gomag create-order payload."""
    payload: dict = {}
    if order.external_id:
        payload["reference"] = order.external_id
    if order.created_at:
        payload["date"] = order.created_at.strftime("%Y-%m-%d")
    if order.currency:
        payload["currency"] = order.currency
    if order.payment_type:
        # Reverse-lookup from the framework PaymentType to a Gomag string
        reverse_payment = {v: k for k, v in GOMAG_PAYMENT_METHOD_MAP.items()}
        payload["payment_method"] = reverse_payment.get(order.payment_type, "")
    if order.total:
        payload["total"] = str(order.total)

    # Billing contact
    if order.billing:
        parts = order.billing.name.split(" ", 1)
        payload["firstname"] = parts[0]
        payload["lastname"] = parts[1] if len(parts) > 1 else ""
        payload["email"] = order.billing.email
        payload["telephone"] = order.billing.phone
        payload["company"] = order.billing.company_name
        if order.billing.address:
            payload["payment_address_1"] = order.billing.address.street
            payload["payment_city"] = order.billing.address.city
            payload["payment_zone"] = order.billing.address.region
            payload["payment_postcode"] = order.billing.address.postal_code
            payload["payment_country"] = order.billing.address.country

    # Shipping contact
    if order.shipping:
        parts = order.shipping.name.split(" ", 1)
        payload["shipping_firstname"] = parts[0]
        payload["shipping_lastname"] = parts[1] if len(parts) > 1 else ""
        if order.shipping.address:
            payload["shipping_address_1"] = order.shipping.address.street
            payload["shipping_city"] = order.shipping.address.city
            payload["shipping_zone"] = order.shipping.address.region
            payload["shipping_postcode"] = order.shipping.address.postal_code
            payload["shipping_country"] = order.shipping.address.country

    # Line items
    if order.items:
        payload["products"] = [
            {
                "product_id": item.product_id,
                "product_name": item.name,
                "sku": item.sku,
                "quantity": int(item.quantity),
                "price": str(item.unit_price),
            }
            for item in order.items
        ]

    return payload


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

    product_id = str(data.get("product_id") or data.get("id", ""))

    return Product(
        product_id=product_id,
        sku=data.get("sku", data.get("model", "")),
        name=data.get("name", ""),
        description=data.get("description", ""),
        price=price,
        currency="",  # Gomag doesn't return currency per product
        stock=int(data["stock"]) if data.get("stock") is not None else (int(data["quantity"]) if data.get("quantity") is not None else None),
        active=data.get("enabled", str(data.get("status", "1"))) not in ("0", False),
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
    raw_products = _normalize_gomag_list(response, key="products")
    products = [product_from_gomag(p) for p in raw_products]
    has_more = len(raw_products) > 0 and len(raw_products) >= 100
    return PaginatedResult(
        items=products,
        cursor=str(page + 1) if has_more else None,
        has_more=has_more,
        total=None,
    )


# ── Outbound: Product → Gomag ──


def _multilang(value: str, lang: str = DEFAULT_LANG) -> dict[str, str]:
    """Wrap a plain string in Gomag's multilingual dict format."""
    return {lang: value}


def product_to_gomag(product: Product, *, lang: str = DEFAULT_LANG) -> dict:
    """Map a Product DTO to a Gomag create payload (single-item list element)."""
    payload: dict = {}
    if product.name:
        payload["name"] = _multilang(product.name, lang)
    if product.description:
        payload["description"] = _multilang(product.description, lang)
    if product.sku:
        payload["sku"] = product.sku
    if product.price is not None:
        payload["price"] = str(product.price)
    if product.stock is not None:
        payload["quantity"] = product.stock
    if product.active is not None:
        payload["status"] = "1" if product.active else "0"
    if product.category_ids:
        payload["category"] = product.category_ids
    elif product.categories:
        payload["category"] = product.categories
    if product.photos:
        payload["image"] = product.photos[0].url
    payload.update(product.extra)
    return payload


def product_update_to_gomag(update: ProductUpdate, *, lang: str = DEFAULT_LANG) -> dict:
    """Map a ProductUpdate DTO to a Gomag patch payload."""
    payload: dict = {"product_id": update.product_id}
    if update.sku is not None:
        payload["sku"] = update.sku
    if update.name is not None:
        payload["name"] = _multilang(update.name, lang)
    if update.description is not None:
        payload["description"] = _multilang(update.description, lang)
    if update.price is not None:
        payload["price"] = str(update.price)
    if update.stock is not None:
        payload["quantity"] = update.stock
    if update.active is not None:
        payload["status"] = "1" if update.active else "0"
    if update.categories is not None:
        payload["category"] = update.categories
    if update.photos is not None and update.photos:
        payload["image"] = update.photos[0].url
    payload.update(update.extra)
    return payload


def inventory_item_to_gomag(
    sku: str,
    *,
    price: Decimal | None = None,
    stock: int | None = None,
    special_price: Decimal | None = None,
) -> dict:
    """Build one entry for the ``/product/inventory/json`` bulk endpoint."""
    item: dict = {"sku": sku}
    if price is not None:
        item["price"] = str(price)
    if stock is not None:
        item["quantity"] = stock
    if special_price is not None:
        item["special_price"] = str(special_price)
    return item


def bulk_updates_to_gomag(updates: list[ProductUpdate]) -> tuple[list[dict], BulkResult]:
    """Convert a list of ProductUpdate DTOs to Gomag inventory payloads.

    Returns the payload list and a pre-filled BulkResult (errors populated
    for items that cannot be mapped — e.g. missing SKU).
    """
    items: list[dict] = []
    errors: list[dict] = []
    for u in updates:
        sku = u.sku or u.product_id
        if not sku:
            errors.append({"product_id": u.product_id, "error": "No SKU available for inventory sync"})
            continue
        items.append(inventory_item_to_gomag(sku, price=u.price, stock=u.stock))
    return items, BulkResult(total=len(updates), succeeded=len(items), failed=len(errors), errors=errors)


# ── Category mappers ──


def category_from_gomag(data: dict) -> ProductCategory:
    """Map a single Gomag category to a ProductCategory DTO."""
    cat_id = str(data.get("category_id") or data.get("id", ""))
    parents = data.get("parents", {})
    parent_id = None
    if isinstance(parents, dict) and parents:
        # Last parent in dict is the direct parent
        parent_id = str(list(parents.keys())[-1])
    elif data.get("parent_id"):
        parent_id = str(data["parent_id"])
    return ProductCategory(
        category_id=cat_id,
        name=data.get("name", ""),
        parent_id=parent_id,
        extra={
            k: v for k, v in data.items() if k not in ("category_id", "id", "name", "parent_id", "parents")
        },
    )


def categories_from_gomag(response: dict | list) -> list[ProductCategory]:
    """Map a Gomag categories response to a list of ProductCategory DTOs."""
    raw = _normalize_gomag_list(response, key="categories")
    return [category_from_gomag(c) for c in raw]


# ── AWB / Shipping mappers ──


def awb_from_gomag(data: dict) -> AWBLabel:
    """Map a Gomag AWB record to an AWBLabel DTO."""
    return AWBLabel(
        tracking_number=data.get("awb_number", data.get("awbNumber", "")),
        label_url=data.get("label_url", data.get("labelUrl", "")),
        extra={
            k: v
            for k, v in data.items()
            if k not in ("awb_number", "awbNumber", "label_url", "labelUrl")
        },
    )


def carrier_from_gomag(data: dict) -> dict:
    """Normalize a Gomag carrier record to a simple dict."""
    return {
        "carrier_id": str(data.get("carrier_id", data.get("carrierId", ""))),
        "name": data.get("name", ""),
        "extra": {
            k: v for k, v in data.items() if k not in ("carrier_id", "carrierId", "name")
        },
    }


def carriers_from_gomag(response: dict | list) -> list[dict]:
    """Map a Gomag carriers response to a list of carrier dicts."""
    raw = _normalize_gomag_list(response)
    return [carrier_from_gomag(c) for c in raw]


def awbs_from_gomag(response: dict | list) -> list[AWBLabel]:
    """Map a Gomag AWBs response to a list of AWBLabel DTOs."""
    raw = _normalize_gomag_list(response)
    return [awb_from_gomag(a) for a in raw]


# ── Attribute mappers ──


def attribute_from_gomag(data: dict) -> AttributeDefinition:
    """Map a Gomag attribute to an AttributeDefinition DTO."""
    values = []
    for v in data.get("values", []):
        name = v.get("name", "")
        if isinstance(name, dict):
            name = next(iter(name.values()), "")
        values.append(
            AttributeValue(
                value_id=str(v.get("id", v.get("value_id", ""))),
                name=name,
            )
        )

    attr_name = data.get("name", "")
    if isinstance(attr_name, dict):
        attr_name = next(iter(attr_name.values()), "")

    return AttributeDefinition(
        attribute_id=str(data.get("id", data.get("attribute_id", ""))),
        name=attr_name,
        attribute_type=data.get("type", "select"),
        values=values,
        extra={
            k: v
            for k, v in data.items()
            if k not in ("id", "attribute_id", "name", "type", "values")
        },
    )


def attributes_from_gomag(response: dict | list) -> list[AttributeDefinition]:
    """Map a Gomag attributes response to a list of AttributeDefinition DTOs."""
    raw = _normalize_gomag_list(response, key="attributes")
    return [attribute_from_gomag(a) for a in raw]


def attribute_to_gomag(attr: AttributeDefinition, *, lang: str = DEFAULT_LANG) -> dict:
    """Map an AttributeDefinition DTO to a Gomag create/update payload."""
    payload: dict = {}
    if attr.attribute_id:
        payload["id"] = attr.attribute_id
    if attr.name:
        payload["name"] = _multilang(attr.name, lang)
    if attr.attribute_type:
        payload["type"] = attr.attribute_type
    if attr.values:
        payload["values"] = [
            {"name": _multilang(v.name, lang)} for v in attr.values
        ]
    return payload


# ── Customer mappers ──


def customer_from_gomag(data: dict) -> Contact:
    """Map a Gomag customer record to a Contact DTO."""
    first = data.get("firstname", "").strip()
    last = data.get("lastname", "").strip()
    name = f"{first} {last}".strip()
    address = None
    street = data.get("address_1", "")
    if street or data.get("city"):
        address = Address(
            street=street,
            city=data.get("city", "").strip(),
            region=data.get("zone", "").strip(),
            postal_code=data.get("postcode", "").strip(),
            country=data.get("country", "").upper().strip(),
        )
    return Contact(
        name=name,
        company_name=data.get("company", "").strip(),
        email=data.get("email", "").lower().strip() if data.get("email") else "",
        phone=data.get("telephone", data.get("phone", "")).strip(),
        address=address,
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "firstname",
                "lastname",
                "company",
                "email",
                "telephone",
                "phone",
                "address_1",
                "city",
                "zone",
                "postcode",
                "country",
            )
        },
    )


def customers_from_gomag(response: dict | list) -> list[Contact]:
    """Map a Gomag customers response to a list of Contact DTOs."""
    raw = _normalize_gomag_list(response)
    return [customer_from_gomag(c) for c in raw]


# ── Payment method mappers ──


def payment_methods_from_gomag(response: dict | list) -> list[dict]:
    """Map a Gomag payment methods response to a list of dicts."""
    return _normalize_gomag_list(response)
