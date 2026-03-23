"""
PrestaShop <-> DTO mappers.

Converts between raw PrestaShop API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.dto import (
    Address,
    AttributeDefinition,
    AttributeValue,
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    PaymentType,
    Product,
    ProductCategory,
    ProductVariant,
    ProviderMeta,
)


def _parse_datetime(value: str) -> datetime | None:
    """Parse ISO datetime string without dateutil dependency."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


# ── Status mappings ──

# PrestaShop order states vary by installation, these are common defaults:
# 1=Awaiting check payment, 2=Payment accepted, 3=Processing, 4=Shipped,
# 5=Delivered, 6=Cancelled, 7=Refunded, 8=Payment error, 9=On backorder
PRESTASHOP_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "1": OrderStatus.PENDING,
    "2": OrderStatus.ACCEPTED,
    "3": OrderStatus.PROCESSING,
    "4": OrderStatus.SHIPPED,
    "5": OrderStatus.DELIVERED,
    "6": OrderStatus.CANCELLED,
    "7": OrderStatus.REFUNDED,
    "8": OrderStatus.CANCELLED,
    "9": OrderStatus.PENDING,
    "10": OrderStatus.PENDING,  # Awaiting bank wire
    "11": OrderStatus.PROCESSING,  # Remote payment accepted
    "12": OrderStatus.PROCESSING,  # On backorder (paid)
}

ORDER_STATUS_TO_PS: dict[OrderStatus, str] = {
    OrderStatus.PENDING: "1",
    OrderStatus.ACCEPTED: "2",
    OrderStatus.PROCESSING: "3",
    OrderStatus.SHIPPED: "4",
    OrderStatus.DELIVERED: "5",
    OrderStatus.CANCELLED: "6",
    OrderStatus.REFUNDED: "7",
    OrderStatus.RETURNED: "7",
}

PRESTASHOP_PAYMENT_TYPE_MAP: dict[str, PaymentType] = {
    "euplatesc": PaymentType.ONLINE_CARD,
    "ps_wirepayment": PaymentType.PAYMENT_ORDER,
    "ps_cashondelivery": PaymentType.CASH_ON_DELIVERY,
    "cargus": PaymentType.CASH_ON_DELIVERY,
    "ramburs": PaymentType.CASH_ON_DELIVERY,
    "ps_checkpayment": PaymentType.PAYMENT_ORDER,
}

PRESTASHOP_PERMISSIONS_REQUIRED = [
    "addresses",
    "countries",
    "customers",
    "orders",
    "products",
    "categories",
    "taxes",
    "images",
]


# ── Helpers ──


def _extract_multilang_name(name_field: dict | str) -> str:
    """Extract name from PrestaShop multilingual field format."""
    if isinstance(name_field, str):
        return name_field
    if isinstance(name_field, dict):
        language = name_field.get("language", "")
        if isinstance(language, dict):
            return language.get("value", "")
        if isinstance(language, list) and language:
            return language[0].get("value", "")
    return ""


def _format_address(address_data: dict, city: str = "", state: str = "") -> str:
    """Format address parts into a single string."""
    parts = []
    if addr1 := address_data.get("address1", ""):
        parts.append(addr1)
    if addr2 := address_data.get("address2", ""):
        parts.append(addr2)
    if city:
        parts.append(city)
    if state:
        parts.append(state)
    if postcode := address_data.get("postcode", ""):
        parts.append(postcode)
    return ", ".join(parts)


# ── Contact / Address mappers ──


def map_address(address_data: dict, country_iso: str = "", state_name: str = "") -> Address:
    """Map a PrestaShop address to a normalized Address DTO."""
    return Address(
        street=_format_address(address_data, city=address_data.get("city", ""), state=state_name),
        city=address_data.get("city", "").strip(),
        region=state_name,
        postal_code=address_data.get("postcode", "").strip(),
        country=country_iso.upper().strip() if country_iso else "",
    )


def map_contact(
    address_data: dict,
    customer_data: dict | None = None,
    country_iso: str = "",
    state_name: str = "",
) -> Contact:
    """Map PrestaShop address + customer data to a normalized Contact DTO."""
    if customer_data:
        name = f"{customer_data.get('firstname', '')} {customer_data.get('lastname', '')}".strip()
        email = customer_data.get("email", "").strip()
    else:
        name = f"{address_data.get('firstname', '')} {address_data.get('lastname', '')}".strip()
        email = ""

    phone = address_data.get("phone", "") or address_data.get("phone_mobile", "")

    return Contact(
        name=name,
        company_name=address_data.get("company", "").strip() if address_data.get("company") else "",
        vat_id=address_data.get("vat_number", "").strip() if address_data.get("vat_number") else "",
        email=email.lower().strip() if email else "",
        phone=phone.strip() if phone else "",
        address=map_address(address_data, country_iso=country_iso, state_name=state_name),
    )


# ── Order mappers ──


def order_from_prestashop(
    data: dict,
    delivery_address: dict | None = None,
    invoice_address: dict | None = None,
    customer: dict | None = None,
    delivery_country_iso: str = "",
    delivery_state_name: str = "",
    invoice_country_iso: str = "",
    invoice_state_name: str = "",
) -> Order:
    """Map a PrestaShop order response to a normalized Order DTO.

    Because PrestaShop requires separate API calls for addresses, customer, etc.,
    those enrichment dicts are passed in separately (fetched by the adapter).
    """
    items = []
    products = []

    # Extract order rows from associations
    # Handles both nested {"order_rows": {"order_row": [...]}} and flat {"order_rows": [...]}
    associations = data.get("associations", {})
    order_rows = associations.get("order_rows", {})
    if order_rows:
        if isinstance(order_rows, list):
            products = order_rows
        else:
            raw_rows = order_rows.get("order_row", [])
            if isinstance(raw_rows, dict):
                raw_rows = [raw_rows]
            products = raw_rows

    for row in products:
        items.append(
            OrderItem(
                item_id=str(row.get("id", "")),
                product_id=row.get("product_reference", ""),
                sku=row.get("product_reference", ""),
                name=row.get("product_name", ""),
                quantity=Decimal(str(row.get("product_quantity", 1))),
                unit_price=Decimal(str(row.get("unit_price_tax_incl", 0))),
                currency="",  # PrestaShop doesn't include currency per line
            )
        )

    # Shipping cost as an extra line item
    shipping_cost = Decimal(str(data.get("total_shipping_tax_incl", "0")))
    if shipping_cost:
        items.append(
            OrderItem(
                item_id="shipping",
                product_id="shipping",
                name="Shipping",
                quantity=Decimal("1"),
                unit_price=shipping_cost,
                extra={"is_transport": True},
            )
        )

    order_date = None
    if date_str := data.get("date_add"):
        order_date = _parse_datetime(date_str)

    raw_status = str(data.get("current_state", ""))
    status = PRESTASHOP_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING)
    payment_module = str(data.get("module", "")).lower()
    payment_type = PRESTASHOP_PAYMENT_TYPE_MAP.get(payment_module, PaymentType.OTHER)

    # Build billing contact
    billing = None
    if invoice_address:
        billing = map_contact(
            invoice_address,
            customer_data=customer,
            country_iso=invoice_country_iso,
            state_name=invoice_state_name,
        )

    # Build shipping contact
    shipping = None
    shipping_addr_dto = None
    delivery_address_str = ""
    if delivery_address:
        shipping = map_contact(
            delivery_address,
            customer_data=customer,
            country_iso=delivery_country_iso,
            state_name=delivery_state_name,
        )
        shipping_addr_dto = map_address(
            delivery_address,
            country_iso=delivery_country_iso,
            state_name=delivery_state_name,
        )
        delivery_address_str = _format_address(
            delivery_address,
            city=delivery_address.get("city", ""),
            state=delivery_state_name,
        )

    return Order(
        order_id=str(data.get("id", "")),
        external_id=data.get("reference"),
        status=status,
        raw_status=raw_status,
        payment_status=PaymentStatus.PAID
        if status not in (OrderStatus.PENDING, OrderStatus.CANCELLED)
        else PaymentStatus.UNPAID,
        payment_type=payment_type,
        currency="",  # PrestaShop order doesn't always expose currency directly
        items=items,
        billing=billing,
        shipping=shipping,
        shipping_address=shipping_addr_dto,
        delivery_address=delivery_address_str,
        total=Decimal(str(data.get("total_paid_tax_incl", 0))),
        created_at=order_date,
        provider_meta=ProviderMeta(
            provider="prestashop",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "id",
                "reference",
                "current_state",
                "module",
                "date_add",
                "total_paid_tax_incl",
                "total_shipping_tax_incl",
                "associations",
                "id_customer",
                "id_address_delivery",
                "id_address_invoice",
            )
        },
    )


def orders_from_prestashop(orders: list[Order]) -> PaginatedResult[Order]:
    """Wrap a list of mapped PrestaShop orders in a PaginatedResult."""
    return PaginatedResult(
        items=orders,
        cursor=None,
        has_more=False,
        total=len(orders),
    )


# ── Product mappers ──


def product_from_prestashop(data: dict) -> Product:
    """Map a PrestaShop product response to a normalized Product DTO."""
    name = _extract_multilang_name(data.get("name", ""))

    return Product(
        product_id=str(data.get("id", "")),
        sku=data.get("reference", ""),
        barcode=data.get("ean13", ""),
        name=name,
        price=Decimal(str(data.get("price", 0))) if data.get("price") else None,
        currency="",  # PrestaShop doesn't return currency per product
        stock=int(data["stock_quantity"]) if data.get("stock_quantity") is not None else None,
        active=str(data.get("active", "1")) == "1",
        categories=[str(data.get("id_category_default", ""))] if data.get("id_category_default") else [],
        provider_meta=ProviderMeta(
            provider="prestashop",
            raw_id=str(data.get("id", "")),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in (
                "id",
                "reference",
                "ean13",
                "name",
                "price",
                "stock_quantity",
                "active",
                "id_category_default",
            )
        },
    )


def products_from_prestashop(results: list[dict]) -> PaginatedResult[Product]:
    """Map a list of PrestaShop product results to PaginatedResult[Product]."""
    products = [product_from_prestashop(p) for p in results]
    return PaginatedResult(
        items=products,
        cursor=None,
        has_more=False,
        total=len(products),
    )


# ── Category mappers ──


def category_from_prestashop(data: dict) -> ProductCategory:
    """Map a PrestaShop category to a normalized ProductCategory DTO."""
    name = _extract_multilang_name(data.get("name", ""))
    parent_id = data.get("id_parent")
    if parent_id and int(parent_id) == 0:
        parent_id = None

    return ProductCategory(
        category_id=str(data.get("id", "")),
        name=name,
        parent_id=str(parent_id) if parent_id else None,
        extra={k: v for k, v in data.items() if k not in ("id", "name", "id_parent")},
    )


def categories_from_prestashop(results: list[dict]) -> list[ProductCategory]:
    """Map a list of PrestaShop categories."""
    return [category_from_prestashop(c) for c in results]


# ── Attribute mappers (features + product options) ──


def attribute_from_prestashop_feature(feature: dict, values: list[dict] | None = None) -> AttributeDefinition:
    """Map a PrestaShop product_feature to AttributeDefinition."""
    name = _extract_multilang_name(feature.get("name", ""))
    attr_values = []
    for v in (values or []):
        val_name = _extract_multilang_name(v.get("value", ""))
        attr_values.append(AttributeValue(value_id=str(v.get("id", "")), name=val_name))
    return AttributeDefinition(
        attribute_id=str(feature.get("id", "")),
        name=name,
        attribute_type="feature",
        values=attr_values,
        extra={"kind": "feature"},
    )


def attribute_from_prestashop_option(option: dict, values: list[dict] | None = None) -> AttributeDefinition:
    """Map a PrestaShop product_option to AttributeDefinition."""
    name = _extract_multilang_name(option.get("name", "")) or _extract_multilang_name(option.get("public_name", ""))
    attr_values = []
    for v in (values or []):
        val_name = _extract_multilang_name(v.get("name", ""))
        attr_values.append(AttributeValue(value_id=str(v.get("id", "")), name=val_name))
    return AttributeDefinition(
        attribute_id=str(option.get("id", "")),
        name=name,
        attribute_type="select",
        values=attr_values,
        extra={"kind": "option", "group_type": option.get("group_type", "select")},
    )


# ── Variant mappers (combinations) ──


def variant_from_prestashop(combination: dict, option_values_map: dict | None = None) -> ProductVariant:
    """Map a PrestaShop combination to ProductVariant DTO.

    option_values_map: {option_value_id: {"name": "Red", "group_name": "Color"}}
    """
    option_values_map = option_values_map or {}
    attributes: dict = {}

    # Extract associations.product_option_values
    assoc = combination.get("associations", {})
    pov = assoc.get("product_option_values", [])
    if isinstance(pov, dict):
        pov = pov.get("product_option_value", [])
    if isinstance(pov, dict):
        pov = [pov]
    if isinstance(pov, list):
        for item in pov:
            val_id = str(item.get("id", ""))
            if val_id in option_values_map:
                info = option_values_map[val_id]
                attributes[info.get("group_name", "")] = info.get("name", "")

    price_impact = Decimal(str(combination.get("price", 0)))

    return ProductVariant(
        variant_id=str(combination.get("id", "")),
        sku=combination.get("reference", ""),
        barcode=combination.get("ean13", ""),
        price=price_impact if price_impact else None,  # delta, not absolute
        stock=int(combination.get("quantity", 0)) if combination.get("quantity") is not None else None,
        attributes=attributes,
        extra={"price_is_delta": True},
    )


# ── Outbound product mappers (local → PrestaShop) ──


def _multilang(value: str, lang_id: int = 1) -> dict:
    """Wrap a string in PrestaShop multilang format."""
    return {"language": [{"attrs": {"id": str(lang_id)}, "value": value}]}


def product_to_prestashop(product, price_to_provider=None) -> dict:
    """Map a Product DTO to a PrestaShop product payload for create/update."""
    data: dict = {
        "name": _multilang(product.name),
        "active": "1" if product.active else "0",
    }
    if product.description:
        data["description"] = _multilang(product.description)
    if product.sku:
        data["reference"] = product.sku
    if product.barcode:
        data["ean13"] = product.barcode
    if product.price is not None:
        convert = price_to_provider or (lambda x: x)
        data["price"] = str(convert(product.price))
    if product.categories:
        # Use first category as default
        data["id_category_default"] = product.categories[0]
    return data


def product_update_to_prestashop(update, price_to_provider=None) -> dict:
    """Map a ProductUpdate DTO to a PrestaShop product update payload."""
    data: dict = {"id": int(update.product_id)}
    if update.name is not None:
        data["name"] = _multilang(update.name)
    if update.description is not None:
        data["description"] = _multilang(update.description)
    if update.sku is not None:
        data["reference"] = update.sku
    if update.price is not None:
        convert = price_to_provider or (lambda x: x)
        data["price"] = str(convert(update.price))
    if update.active is not None:
        data["active"] = "1" if update.active else "0"
    if update.extra:
        data.update(update.extra)
    return data
