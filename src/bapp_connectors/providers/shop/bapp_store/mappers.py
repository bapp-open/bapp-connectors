"""
Company Store <-> DTO mappers.

Outbound records follow the CatalogSyncTask contract (fixtures/products_batch.json);
inbound rows come from the store's public content-type viewsets.
"""

from __future__ import annotations

from decimal import Decimal
from html.parser import HTMLParser

from bapp_connectors.core.dto import Product, ProductPhoto, ProductUpdate
from bapp_connectors.core.pricing import to_gross

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
