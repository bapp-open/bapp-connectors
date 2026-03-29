"""
eMAG shop adapter — implements ShopPort + BulkUpdateCapability + InvoiceAttachmentCapability.

This is the main entry point for the eMAG integration.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import BulkUpdateCapability, InvoiceAttachmentCapability, WebhookCapability
from bapp_connectors.core.dto import (
    BulkResult,
    ConnectionTestResult,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductUpdate,
)
from bapp_connectors.core.dto.webhook import WebhookEvent
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.status_mapping import StatusMapper
from bapp_connectors.providers.shop.emag.client import EmagApiClient
from bapp_connectors.providers.shop.emag.errors import EmagIPWhitelistError
from bapp_connectors.providers.shop.emag.manifest import EMAG_BASE_URLS, manifest
from bapp_connectors.providers.shop.emag.mappers import (
    EMAG_ORDER_STATUS_MAP,
    ORDER_STATUS_TO_EMAG,
    order_from_emag,
    orders_from_emag,
    products_from_emag,
    webhook_event_from_emag,
)

# eMAG enforces a maximum stock value
EMAG_MAX_STOCK = 65535

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class EmagShopAdapter(ShopPort, BulkUpdateCapability, InvoiceAttachmentCapability, WebhookCapability):
    """
    eMAG marketplace adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - BulkUpdateCapability: batch product updates
    - InvoiceAttachmentCapability: attach invoices to orders
    - WebhookCapability: IPN callback parsing (no signature verification)
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.country = credentials.get("country", "RO")

        # Resolve base URL for the configured country
        base_url = EMAG_BASE_URLS.get(self.country, EMAG_BASE_URLS["RO"])

        if http_client is None:
            from bapp_connectors.core.http import BasicAuth

            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(credentials.get("username", ""), credentials.get("password", "")),
                provider_name="emag",
            )
        else:
            # Override the base_url on the provided http_client for the correct country
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = EmagApiClient(http_client=http_client)

        self._status_mapper = StatusMapper.from_config(
            default_inbound=EMAG_ORDER_STATUS_MAP,
            default_outbound=ORDER_STATUS_TO_EMAG,
            config=config,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except EmagIPWhitelistError as e:
            return ConnectionTestResult(
                success=False,
                message=str(e),
                details={"error_type": "ip_whitelist"},
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── ShopPort ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 1
        kwargs: dict = {}
        if since is not None:
            kwargs["created_after"] = since.strftime("%Y-%m-%d %H:%M")
        response = self.client.get_orders(page=page, **kwargs)
        return orders_from_emag(response, country=self.country, status_mapper=self._status_mapper)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return order_from_emag(data, country=self.country, status_mapper=self._status_mapper)

    def acknowledge_order(self, order_id: str) -> None:
        """Acknowledge an order (move to 'in progress' status on eMAG)."""
        self.client.order_acknowledge(int(order_id))

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        return products_from_emag(response)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        clamped = min(quantity, EMAG_MAX_STOCK)
        self.client.update_product(
            [
                {
                    "part_number": product_id,
                    "stock": [{"warehouse_id": 1, "value": clamped}],
                }
            ]
        )

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        from decimal import Decimal as _Decimal

        sale_price = price
        min_price = sale_price
        max_price = (sale_price * _Decimal("1.5")).quantize(_Decimal("0.01"))
        self.client.update_product(
            [
                {
                    "part_number": product_id,
                    "sale_price": str(sale_price),
                    "min_sale_price": str(min_price),
                    "max_sale_price": str(max_price),
                }
            ]
        )

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        emag_status = self._status_mapper.to_provider(status)
        if not emag_status:
            raise ValueError(f"Cannot map OrderStatus.{status} to an eMAG status")
        self.client.update_order_status(int(order_id), status=int(emag_status))
        return self.get_order(order_id)

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        from decimal import Decimal as _Decimal

        items = []
        for update in updates:
            item: dict = {"part_number": update.barcode or update.product_id}

            if update.price is not None:
                item["sale_price"] = str(update.price)
                item["min_sale_price"] = str(update.price)
                item["max_sale_price"] = str((update.price * _Decimal("1.5")).quantize(_Decimal("0.01")))
            if update.stock is not None:
                item["stock"] = [{"warehouse_id": 1, "value": min(update.stock, EMAG_MAX_STOCK)}]
            if update.name is not None:
                item["name"] = update.name

            items.append(item)

        succeeded = 0
        errors = []

        # eMAG product_offer/save accepts a batch of items
        if items:
            try:
                self.client.update_product(items)
                succeeded = len(items)
            except Exception as e:
                errors.append({"type": "product_offer_save", "error": str(e), "count": len(items)})

        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
        )

    # ── InvoiceAttachmentCapability ──

    def attach_invoice(self, order_id: str, invoice_url: str, name: str = "", attachment_type: int = 1) -> bool:
        """Attach a document to an order.

        attachment_type: 1=invoice, 3=warranty, 4=user manual, 8=user guide,
                         10=AWB, 11=proforma
        """
        try:
            self.client.order_attachment_save(
                order_id=int(order_id),
                attachment_url=invoice_url,
                attachment_name=name,
                attachment_type=attachment_type,
            )
            return True
        except Exception:
            return False

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        # eMAG does not sign webhook payloads — always return True
        return True

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        payload = json.loads(body) if body else {}
        # eMAG IPN sends the event code as a URL path segment (e.g. /order.created)
        # which arrives as a parameter. The code is typically in the payload or passed externally.
        event_code = payload.get("event", payload.get("action", ""))
        return webhook_event_from_emag(event_code, payload)

    # ── AWB ──

    def generate_awb(self, awb_data: dict) -> dict:
        """
        Generate AWB via eMAG.

        awb_data should contain: order_id, sender, receiver, cod, parcel_number, etc.
        See eMAG API docs for the full awb/save payload format.

        Returns the raw eMAG AWB response results.
        """
        response = self.client.generate_awb(awb_data)
        return response.results[0] if response.results else {}

    def read_awb(self, emag_id: int | None = None, reservation_id: int | None = None) -> dict:
        """Read AWB details by eMAG ID or reservation ID."""
        response = self.client.read_awb(emag_id=emag_id, reservation_id=reservation_id)
        return response.results[0] if response.results else {}

    def read_awb_pdf(self, order_id: str, pdf_format: str = "A4") -> bytes:
        """Download AWB PDF for an order."""
        return self.client.read_awb_pdf(int(order_id), pdf_format=pdf_format)

    def get_locality_id(self, region: str, locality: str, country: str | None = None) -> int:
        """Look up a locality ID for AWB sender/receiver addresses."""
        response = self.client.get_locality(
            region=region,
            name=locality,
            country=country or self.country,
        )
        if not response.results:
            raise ValueError(f"No locality found for region={region}, locality={locality}")
        return response.results[0]["emag_id"]
