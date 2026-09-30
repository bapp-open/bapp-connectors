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

from bapp_connectors.core.dto import ConnectionTestResult, Order, OrderStatus, PaginatedResult, Product
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.altex.client import AltexApiClient
from bapp_connectors.providers.shop.altex.manifest import ALTEX_LIVE_URL, ALTEX_STAGING_URL, manifest
from bapp_connectors.providers.shop.altex.mappers import ALTEX_STATUS_CODES, order_from_altex, product_from_offer

if TYPE_CHECKING:
    from decimal import Decimal

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
# cancellationReason: 0 Default, 1 Out of stock, 2 Price error, 3 Logistics issues
CANCELLATION_REASONS = {"default": 0, "out_of_stock": 1, "price_error": 2, "logistics": 3}


class AltexShopAdapter(ShopPort):
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

    # ── Documents (Altex-specific) ──

    def upload_invoice(self, order_id: str, pdf: bytes, invoice_number: str, name: str = "",
                       line_ids: list | None = None) -> None:
        """Attach the invoice PDF (max 2 MB) to the order lines; all lines when none are given."""
        if line_ids is None:
            line_ids = [item.item_id for item in self.get_order(order_id).items]
        self.client.upload_invoice(order_id, pdf, invoice_number, name or f"Factura {invoice_number}", line_ids)

    def attach_awb(self, order_id: str, pdf: bytes, number: str, courier: str) -> None:
        """Attach an AWB generated elsewhere; `courier` is matched by name to Altex's courier list."""
        couriers = self.client.couriers()
        wanted = courier.lower().replace(" ", "")
        match = next((c for c in couriers if str(c.get("name", "")).lower().replace(" ", "") in (wanted, f"{wanted}courier")
                      or wanted in str(c.get("name", "")).lower().replace(" ", "")), None)
        if not match:
            raise ValidationError(f"Altex has no courier matching {courier!r}: {[c.get('name') for c in couriers]}")
        self.client.attach_awb(order_id, pdf, number, int(match["id"]))
