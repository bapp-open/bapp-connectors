"""
Altex Marketplace adapter — implements ShopPort.

No order webhooks: orders are polled (the list only filters by order date, so
`get_orders(since)` reads from that date to today). The list carries summaries only;
each order is read in full for its lines. Prices include VAT; currency is RON.
Invoice and own-AWB upload are Altex-specific methods (files, not URLs).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.core.dto import (
    AWBLabel,
    ConnectionTestResult,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ShopReturn,
)
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.altex.client import AltexApiClient
from bapp_connectors.providers.shop.altex.manifest import ALTEX_LIVE_URL, ALTEX_STAGING_URL, manifest
from bapp_connectors.providers.shop.altex.mappers import ALTEX_STATUS_CODES, order_from_altex, product_from_offer
from bapp_connectors.providers.shop.altex.returns import return_from_rma

if TYPE_CHECKING:
    from decimal import Decimal

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
# cancellationReason: 0 Default, 1 Out of stock, 2 Price error, 3 Logistics issues
CANCELLATION_REASONS = {"default": 0, "out_of_stock": 1, "price_error": 2, "logistics": 3}


class AltexShopAdapter(ShopPort, ReturnsCapability):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        days = config.get("order_days")
        self._order_days = 7 if days in (None, "") else max(1, int(days))
        staging = str(credentials.get("staging", "false")).lower() in ("true", "1", "yes")
        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="altex")
        self.client = AltexApiClient(http_client=http_client, base_url=ALTEX_STAGING_URL if staging else ALTEX_LIVE_URL,
                                     public_key=credentials.get("public_key", ""),
                                     private_key=credentials.get("private_key", ""))

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            self.client.list_orders(page=1, per_page=1)
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(success=True, message="Connected")

    # ── Orders ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 1
        start = since or (datetime.now(UTC) - timedelta(days=self._order_days))
        data = self.client.list_orders(start_date=start.strftime("%Y-%m-%d"),
                                       end_date=datetime.now(UTC).strftime("%Y-%m-%d"), page=page, per_page=_PAGE_SIZE)
        orders = [self.get_order(str(item["order_id"])) for item in data.get("items") or [] if item.get("order_id")]
        has_more = int(data.get("current_page") or page) < int(data.get("total_pages") or page)
        return PaginatedResult(items=orders, cursor=str(page + 1) if has_more else None, has_more=has_more,
                               total=data.get("total_items"))

    def get_order(self, order_id: str) -> Order:
        """`order_id` is Altex's numeric id (Order.external_id), not the ATX... code."""
        return order_from_altex(self.client.get_order(order_id))

    def update_order_status(self, order_id: str, status: OrderStatus, reason: str = "default") -> Order:
        code = ALTEX_STATUS_CODES.get(status)
        if code is None:
            raise ValidationError(f"Altex has no status for {status}.")
        cancellation = CANCELLATION_REASONS.get(reason, 0) if code == 7 else None
        self.client.update_order_status(order_id, code, cancellation)
        return self.get_order(order_id)

    def acknowledge_order(self, order_id: str) -> Order:
        """New (1) -> In Progress (2), as sellers confirm receipt."""
        return self.update_order_status(order_id, OrderStatus.ACCEPTED)

    # ── Offers ──

    def get_products(self, cursor: str | None = None, since: datetime | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        data = self.client.list_offers(page=page, per_page=_PAGE_SIZE,
                                       updated_from=since.strftime("%Y-%m-%d") if since else "")
        has_more = int(data.get("current_page") or page) < int(data.get("total_pages") or page)
        return PaginatedResult(items=[product_from_offer(o) for o in data.get("items") or []],
                               cursor=str(page + 1) if has_more else None, has_more=has_more,
                               total=data.get("total_items"))

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        """`product_id` is the offer id (Product.product_id from get_products)."""
        self.client.update_offer_stock(product_id, max(0, int(quantity)))

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        """Sets the offer price, VAT included, and clears the promo so the new price is the one shown
        (Altex requires selling_price <= price)."""
        if currency and currency.upper() != "RON":
            raise ValidationError(f"Altex prices are in RON, not {currency}.")
        value = float(round(price, 2))
        self.client.update_offer(product_id, {"price": value, "selling_price": value})

    # ── Returns (RMA) ──

    def get_returns(self, since: datetime, until: datetime) -> list[ShopReturn]:
        """RMAs created from `since` (Altex filters `created_at >=`, no upper bound); `until` cuts locally.
        Each RMA is read in full, then joined to its order for SKU/price."""
        results: list[ShopReturn] = []
        page = 1
        while True:
            data = self.client.list_rmas(created_from=since.strftime("%Y-%m-%d"), page=page, per_page=_PAGE_SIZE)
            items = data.get("items") or []
            for summary in items:
                rma = self.client.get_rma(str(summary["rma_id"]))
                shop_return = return_from_rma(rma, self._order_for_rma(rma))
                if _after(shop_return.requested_at, until):
                    continue
                results.append(shop_return)
            if int(data.get("current_page") or page) >= int(data.get("total_pages") or page) or not items:
                return results
            page += 1

    def _order_for_rma(self, rma: dict) -> dict | None:
        order_id = rma.get("order_id")
        if not order_id:
            return None
        try:
            return self.client.get_order(str(order_id))
        except Exception:
            logger.debug("Altex: order %s for RMA %s not available", order_id, rma.get("rma_id"))
            return None

    # ── AWB generated by Altex ──

    def generate_awb(self, order_id: str, courier: str, sender: dict, *, packages: int = 1,
                     weight: float = 1.0, declared_value: float = 0.0, dimensions: dict | None = None,
                     apply_insurance: bool = False, label_format: str = "A4") -> AWBLabel:
        """Book the courier through Altex. `courier` is matched by name (must allow AWB generation),
        `sender` carries the pickup address (name, contact_person, phone, address, county, city, postal_code)
        and its Altex location id under `address_id` (from `list_locations`). The destination defaults to
        the order address; pass it in `sender['destination']` to override."""
        courier_id = self._courier_id(courier, for_awb=True)
        address_id = sender.get("address_id") or self._first_location_id(courier_id)
        dims = dimensions or {}
        form = {
            "courier_id": courier_id,
            "address_id": address_id,
            "sender_name": sender.get("name", ""),
            "sender_contact_person": sender.get("contact_person", ""),
            "sender_phone": _digits(sender.get("phone")),
            "sender_address": sender.get("address", ""),
            "sender_county": sender.get("county", ""),
            "sender_city": sender.get("city", ""),
            "sender_postalcode": sender.get("postal_code", ""),
            "order_packages": int(packages),
            "order_weight": weight,
            "order_length": dims.get("length", 1),
            "order_height": dims.get("height", 1),
            "order_size": dims.get("width", 1),
            "declared_value": float(declared_value),
            "order_awb_format": "1" if label_format == "10x14" else "0",
            "apply_insurance": bool(apply_insurance),
        }
        for key, value in (sender.get("destination") or {}).items():
            form[f"destination_{key}"] = value
        result = self.client.generate_awb(order_id, form)
        pdf = None
        document = result.get("document")
        if document:
            import base64
            try:
                pdf = base64.b64decode(document)
            except (ValueError, TypeError):
                pdf = None
        return AWBLabel(tracking_number=str(result.get("awb_number") or ""), label_pdf=pdf,
                        extra={"document_type": result.get("document_type", ""), "courier_id": courier_id})

    def list_locations(self) -> list[dict]:
        """Pickup locations to pass as `sender['address_id']` when generating an AWB."""
        return self.client.locations()

    # ── Documents (Altex-specific) ──

    def upload_invoice(self, order_id: str, pdf: bytes, invoice_number: str, name: str = "",
                       line_ids: list | None = None) -> None:
        """Attach the invoice PDF (max 2 MB) to the order lines; all lines when none are given."""
        if line_ids is None:
            line_ids = [item.item_id for item in self.get_order(order_id).items]
        self.client.upload_invoice(order_id, pdf, invoice_number, name or f"Factura {invoice_number}", line_ids)

    def attach_awb(self, order_id: str, pdf: bytes, number: str, courier: str) -> None:
        """Attach an AWB generated elsewhere; `courier` is matched by name to Altex's courier list."""
        self.client.attach_awb(order_id, pdf, number, self._courier_id(courier))

    # ── Helpers ──

    def _courier_id(self, courier: str, for_awb: bool = False) -> int:
        couriers = self.client.couriers()
        wanted = courier.lower().replace(" ", "")
        for c in couriers:
            name = str(c.get("name", "")).lower().replace(" ", "")
            if wanted and (wanted in name or name in (wanted, f"{wanted}courier")):
                if for_awb and c.get("forGenerateAwb") is False:
                    raise ValidationError(f"Altex courier {c.get('name')!r} does not support AWB generation.")
                return int(c["id"])
        raise ValidationError(f"Altex has no courier matching {courier!r}: {[c.get('name') for c in couriers]}")

    def _first_location_id(self, courier_id: int) -> int:
        for loc in self.client.locations():
            if loc.get("courier_id") in (courier_id, None):
                return int(loc.get("id") or loc.get("courier_location_id"))
        raise ValidationError("Altex has no pickup location for this courier; pass sender['address_id'].")


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:10]


def _after(when: datetime | None, until: datetime) -> bool:
    """`when > until`, tolerating a naive `until` (Altex dates are UTC-aware)."""
    if when is None:
        return False
    if when.tzinfo and until.tzinfo is None:
        until = until.replace(tzinfo=when.tzinfo)
    elif until.tzinfo and when.tzinfo is None:
        when = when.replace(tzinfo=until.tzinfo)
    return when > until
