"""
Trendyol shop adapter — implements ShopPort + BulkUpdateCapability + InvoiceAttachmentCapability + WebhookCapability.

This is the main entry point for the Trendyol integration.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    BulkUpdateCapability,
    FinancialCapability,
    InvoiceAttachmentCapability,
    ShippingCapability,
    WebhookCapability,
)
from bapp_connectors.core.dto import (
    AWBLabel,
    BulkResult,
    ConnectionTestResult,
    FinancialTransaction,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductUpdate,
    WebhookEvent,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.trendyol.client import TrendyolApiClient
from bapp_connectors.providers.shop.trendyol.manifest import TRENDYOL_LIVE_URL, TRENDYOL_STAGING_URL, manifest
from bapp_connectors.providers.shop.trendyol.mappers import (
    order_from_trendyol,
    orders_from_trendyol,
    products_from_trendyol,
    settlements_from_trendyol,
    webhook_event_from_trendyol,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class TrendyolShopAdapter(ShopPort, BulkUpdateCapability, InvoiceAttachmentCapability, WebhookCapability, FinancialCapability, ShippingCapability):
    """
    Trendyol marketplace adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - BulkUpdateCapability: batch product updates
    - InvoiceAttachmentCapability: attach invoices to orders
    - WebhookCapability: register, list, and parse webhooks
    - FinancialCapability: settlements and financial transactions
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.seller_id = str(credentials.get("seller_id", ""))
        self.country = credentials.get("country", "RO")
        self.sandbox = str(credentials.get("sandbox", "false")).lower() in ("true", "1", "yes")

        base_url = TRENDYOL_STAGING_URL if self.sandbox else TRENDYOL_LIVE_URL

        if http_client is None:
            from bapp_connectors.core.http import BasicAuth

            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(credentials.get("username", ""), credentials.get("password", "")),
                provider_name="trendyol",
            )
        else:
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = TrendyolApiClient(
            http_client=http_client,
            seller_id=self.seller_id,
            country=self.country,
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
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── ShopPort ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 0
        kwargs = {}
        if since:
            kwargs["created_after"] = since
        response = self.client.get_orders(page=page, **kwargs)
        return orders_from_trendyol(response)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(order_id)
        return order_from_trendyol(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 0
        response = self.client.get_products(page=page, approved=True)
        return products_from_trendyol(response)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.batch_update_price_inventory([{"barcode": product_id, "quantity": quantity}])

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        self.client.batch_update_price_inventory(
            [
                {"barcode": product_id, "salePrice": str(price), "listPrice": str(price)},
            ]
        )

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        raise NotImplementedError("Order status update is not supported by this provider.")

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        price_inventory_items = []
        product_items = []

        for update in updates:
            item: dict = {"barcode": update.barcode or update.product_id}
            has_name = update.name is not None

            if update.price is not None:
                item["salePrice"] = str(update.price)
                item["listPrice"] = str(update.price)
            if update.stock is not None:
                item["quantity"] = update.stock

            if has_name:
                item["title"] = update.name
                product_items.append(item)
            else:
                price_inventory_items.append(item)

        succeeded = 0
        errors = []

        if price_inventory_items:
            try:
                self.client.batch_update_price_inventory(price_inventory_items)
                succeeded += len(price_inventory_items)
            except Exception as e:
                errors.append({"type": "price_inventory", "error": str(e), "count": len(price_inventory_items)})

        if product_items:
            try:
                self.client.batch_update_products(product_items)
                succeeded += len(product_items)
            except Exception as e:
                errors.append({"type": "product", "error": str(e), "count": len(product_items)})

        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
        )

    # ── ShippingCapability ──

    def get_order_awbs(self, order_id: str) -> list[AWBLabel]:
        data = self.client.get_order(order_id)
        tracking = data.get("cargoTrackingNumber")
        if not tracking:
            return []
        return [AWBLabel(
            tracking_number=str(tracking),
            label_url=data.get("cargoTrackingLink", ""),
            extra={
                "courier": data.get("cargoProviderName", ""),
                "sender_number": data.get("cargoSenderNumber", ""),
                "shipment_package_id": data.get("shipmentPackageId"),
            },
        )]

    def get_awb_pdf(self, awb_id: str) -> bytes:
        """Download AWB label PDF. awb_id is the shipmentPackageId."""
        return self.client.read_awb(int(awb_id))

    # ── InvoiceAttachmentCapability ──

    def attach_invoice(self, order_id: str, invoice_url: str) -> bool:
        try:
            self.client.order_attachment(order_id=int(order_id), invoice_url=invoice_url)
            return True
        except Exception:
            return False

    # ── FinancialCapability ──

    SETTLEMENT_TYPES = ("Sale", "Return")
    OTHER_FINANCIAL_TYPES = (
        "CashAdvance",
        "WireTransfer",
        "IncomingTransfer",
        "ReturnInvoice",
        "CommissionAgreementInvoice",
        "PaymentOrder",
        "DeductionInvoices",
        "FinancialItem",
        "Stoppage",
        "CreditNote",
        "CommissionInvoice",
    )
    ALL_FINANCIAL_TYPES = SETTLEMENT_TYPES + OTHER_FINANCIAL_TYPES

    def get_financial_transactions(
        self,
        start_date: datetime,
        end_date: datetime,
        transaction_type: str | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[FinancialTransaction]:
        """Fetch financial transactions.

        Args:
            transaction_type: "Sale" or "Return" (settlements) or one of the
                OTHER_FINANCIAL_TYPES (other financials). Defaults to "Sale".
        """
        tx_type = transaction_type or "Sale"
        if tx_type not in self.ALL_FINANCIAL_TYPES:
            raise ValueError(
                f"Invalid transaction_type '{tx_type}'. "
                f"Must be one of: {', '.join(self.ALL_FINANCIAL_TYPES)}"
            )
        if tx_type in self.SETTLEMENT_TYPES:
            return self.get_settlements(tx_type, start_date, end_date, cursor=cursor)
        return self.get_other_financials(tx_type, start_date, end_date, cursor=cursor)

    def get_settlements(
        self,
        transaction_type: str,
        start_date: datetime,
        end_date: datetime,
        cursor: str | None = None,
        size: int = 500,
    ) -> PaginatedResult[FinancialTransaction]:
        """Fetch settlement transactions (Sale or Return).

        Args:
            transaction_type: "Sale" or "Return".
            start_date: Start of date range (max 15-day span).
            end_date: End of date range.
            cursor: Page number as string.
            size: Page size (500 or 1000).
        """
        if transaction_type not in self.SETTLEMENT_TYPES:
            raise ValueError(f"Invalid settlement type '{transaction_type}'. Must be one of: {', '.join(self.SETTLEMENT_TYPES)}")
        page = int(cursor) if cursor else 0
        response = self.client.get_settlements(
            transaction_type=transaction_type,
            start_date=int(start_date.timestamp() * 1000),
            end_date=int(end_date.timestamp() * 1000),
            page=page,
            size=size,
        )
        return settlements_from_trendyol(response, query_type=transaction_type)

    def get_other_financials(
        self,
        transaction_type: str,
        start_date: datetime,
        end_date: datetime,
        cursor: str | None = None,
        size: int = 500,
    ) -> PaginatedResult[FinancialTransaction]:
        """Fetch other financial transactions.

        Args:
            transaction_type: One of OTHER_FINANCIAL_TYPES (CashAdvance, WireTransfer,
                IncomingTransfer, ReturnInvoice, CommissionAgreementInvoice, PaymentOrder,
                DeductionInvoices, FinancialItem, Stoppage, CreditNote, CommissionInvoice).
            start_date: Start of date range (max 15-day span).
            end_date: End of date range.
            cursor: Page number as string.
            size: Page size (500 or 1000).
        """
        if transaction_type not in self.OTHER_FINANCIAL_TYPES:
            raise ValueError(
                f"Invalid financial type '{transaction_type}'. "
                f"Must be one of: {', '.join(self.OTHER_FINANCIAL_TYPES)}"
            )
        page = int(cursor) if cursor else 0
        response = self.client.get_other_financials(
            transaction_type=transaction_type,
            start_date=int(start_date.timestamp() * 1000),
            end_date=int(end_date.timestamp() * 1000),
            page=page,
            size=size,
        )
        return settlements_from_trendyol(response, query_type=transaction_type)

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        # Trendyol does not sign webhook payloads — authentication is done
        # via BASIC_AUTHENTICATION or API_KEY on the receiving endpoint.
        return True

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        payload = json.loads(body) if body else {}
        return webhook_event_from_trendyol(payload)

    def register_webhook(self, url: str, events: list[str] | None = None) -> dict:
        statuses = events or [
            "CREATED", "PICKING", "INVOICED", "SHIPPED", "CANCELLED",
            "DELIVERED", "UNDELIVERED", "RETURNED", "UNSUPPLIED", "AWAITING",
        ]
        webhook_data: dict = {
            "url": url,
            "authenticationType": "BASIC_AUTHENTICATION",
            "subscribedStatuses": statuses,
        }
        # Forward auth credentials for the webhook callback endpoint if provided
        config = getattr(self, "_webhook_config", None) or {}
        if config.get("api_key"):
            webhook_data["authenticationType"] = "API_KEY"
            webhook_data["apiKey"] = config["api_key"]
        elif config.get("username"):
            webhook_data["username"] = config["username"]
            webhook_data["password"] = config.get("password", "")
        result = self.client.create_webhook(webhook_data)
        return result if isinstance(result, dict) else {"id": result}

    def list_webhooks(self) -> list[dict]:
        result = self.client.list_webhooks()
        return result if isinstance(result, list) else [result]
