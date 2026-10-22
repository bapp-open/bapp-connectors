"""Temu shop adapter."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    BulkUpdateCapability,
    CustomerDetailsCapability,
    FinancialCapability,
    FulfillmentCapability,
    InvoiceAttachmentCapability,
    OrderAmountCapability,
    OrderLookupCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ReturnsCapability,
    ShippingCapability,
    WebhookCapability,
)
from bapp_connectors.core.dto import ConnectionTestResult, Order, PaginatedResult
from bapp_connectors.core.errors import ConnectorError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.temu.client import DEFAULT_PAGE_SIZE, TemuApiClient
from bapp_connectors.providers.shop.temu.manifest import manifest
from bapp_connectors.providers.shop.temu.mappers import contact_from_shipping_info, order_from_temu
from bapp_connectors.providers.shop.temu.models import SITE_CURRENCY

if TYPE_CHECKING:
    from bapp_connectors.core.capabilities import OrderAmounts
    from bapp_connectors.core.dto import Contact

#: every API this adapter calls; `test_connection` reports the ones the token lacks
REQUIRED_SCOPES = frozenset({
    "bg.open.accesstoken.info.get", "temu.local.mall.settlestatus.get", "bg.logistics.warehouse.list.get",
    "bg.order.list.v2.get", "bg.order.detail.v2.get", "bg.order.shippinginfo.v2.get",
    "bg.order.decryptshippinginfo.get", "temu.order.amount.v2.query",
    "temu.pay.tax.invoice.detail.query", "temu.pay.tax.merchant.upload.invoice",
    "bg.local.goods.list.query", "bg.local.goods.detail.query", "temu.local.goods.v3.add", "temu.local.goods.delete",
    "bg.local.goods.partial.update", "bg.local.goods.stock.edit", "temu.local.goods.sku.stock.query",
    "bg.local.goods.priceorder.change.sku.price",
    "bg.logistics.companies.get", "bg.logistics.shipment.v2.confirm", "bg.logistics.shippingservices.get",
    "bg.logistics.shipment.create", "bg.logistics.shipment.result.get", "bg.logistics.shipment.document.get",
    "bg.logistics.shipped.package.confirm",
    "temu.finance.mall.bill.task.create", "temu.finance.mall.bill.task.get",
    "bg.aftersales.parentaftersales.list.get", "temu.aftersales.parentaftersales.detail.get",
    "bg.aftersales.cancel.list.get", "bg.tmc.message.update",
})


class TemuShopAdapter(
    ShopPort,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    BulkUpdateCapability,
    WebhookCapability,
    InvoiceAttachmentCapability,
    ShippingCapability,
    FulfillmentCapability,
    OrderAmountCapability,
    CustomerDetailsCapability,
    FinancialCapability,
    ReturnsCapability,
    OrderLookupCapability,
):
    """Temu marketplace adapter (Partner Platform open API, local-to-local sellers)."""

    manifest = manifest
    #: Temu downloads product images from the URLs we send; the host keeps batches small
    sideloads_images = True

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}
        self.app_key = str(credentials.get("app_key", ""))
        self.app_secret = str(credentials.get("app_secret", ""))
        self.access_token = str(credentials.get("access_token", ""))
        self.region = str(credentials.get("region") or "eu")
        self.client = TemuApiClient(self.app_key, self.app_secret, self.access_token, region=self.region, http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return all((self.app_key, self.app_secret, self.access_token))

    def test_connection(self) -> ConnectionTestResult:
        try:
            info = self.client.token_info()
            settle = self.client.settle_status()
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        scopes = sorted(info.get("apiScopeList") or [])
        missing = sorted(REQUIRED_SCOPES - set(scopes))
        mall_id = str(info.get("mallId") or settle.get("mallId") or "")
        expires = datetime.datetime.fromtimestamp(int(info.get("expiredTime") or 0), tz=datetime.UTC)
        message = f"{settle.get('mallName') or 'Temu'} (mall {mall_id}), {len(scopes)} permisiuni, token valabil până la {expires:%Y-%m-%d}"
        if missing:
            message += f" — lipsesc: {', '.join(missing)}"
        return ConnectionTestResult(
            success=True,
            message=message,
            details={
                "mall_id": mall_id,
                "mall_name": settle.get("mallName") or "",
                "expires_at": expires.isoformat(),
                "scopes": scopes,
                "missing_scopes": missing,
                "detected_credentials": {"mall_id": mall_id} if mall_id else {},
            },
        )

    def detect_credentials(self) -> dict:
        """Credentials the host may store after a successful connect (the mall id)."""
        try:
            mall_id = str(self.client.token_info().get("mallId") or "")
        except Exception:
            return {}
        return {"mall_id": mall_id} if mall_id else {}

    def default_warehouse_id(self) -> str:
        configured = str(self.config.get("warehouse_id") or "")
        if configured:
            return configured
        warehouses = self.client.warehouses()
        for warehouse in warehouses:
            if warehouse.get("defaultWarehouse"):
                return str(warehouse.get("warehouseId") or "")
        return str(warehouses[0].get("warehouseId") or "") if warehouses else ""

    # ── ShopPort: orders ──

    def _site_currency(self, head: dict) -> str:
        try:
            site_id = int(head.get("siteId") or 0)
        except (TypeError, ValueError):
            site_id = 0
        return SITE_CURRENCY.get(site_id) or str(self.config.get("currency") or "RON")

    def _shipping_or_none(self, order_id: str) -> dict | None:
        try:
            return self.client.shipping_info(order_id) or None
        except ConnectorError:
            return None

    def _amounts_or_none(self, order_id: str) -> OrderAmounts | None:
        try:
            return self.get_order_amounts(order_id)
        except (ConnectorError, NotImplementedError):
            return None

    def get_orders(self, since: datetime.datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        """One list page per call. Every row is enriched with the shipping contact and the amounts
        (2 extra calls per order): the host's pull channel feeds list rows straight into its
        intake, so a bare row would create an order without buyer and without prices."""
        page = int(cursor) if cursor else 1
        data = self.client.list_orders(
            page_number=page,
            page_size=DEFAULT_PAGE_SIZE,
            parent_order_status=0,
            update_at_start=int(since.timestamp()) if since else None,
        )
        rows = data.get("pageItems") or []
        items = []
        for row in rows:
            head = row.get("parentOrderMap") or {}
            order_id = str(head.get("parentOrderSn") or "")
            shipping = self._shipping_or_none(order_id)
            items.append(order_from_temu(row, shipping, self._site_currency(head), self._amounts_or_none(order_id)))
        total = data.get("totalItemNum")
        has_more = bool(rows) and (page * DEFAULT_PAGE_SIZE < int(total) if total is not None else len(rows) == DEFAULT_PAGE_SIZE)
        return PaginatedResult(items=items, cursor=str(page + 1) if has_more else None, has_more=has_more, total=total)

    def get_order(self, order_id: str) -> Order:
        detail = self.client.order_detail(order_id)
        shipping = self.client.shipping_info(order_id)
        amounts = self._amounts_or_none(order_id)
        return order_from_temu(detail, shipping, self._site_currency(detail.get("parentOrderMap") or {}), amounts)

    def get_customer_details(self, order_id: str) -> Contact:
        return contact_from_shipping_info(self.client.decrypt_shipping_info(order_id))

    def find_order_by_reference(self, reference: str) -> Order | None:
        """Only a parent order sn (``PO-…``) can be looked up; a child ``orderSn`` has no detail API."""
        if not str(reference).startswith("PO-"):
            return None
        return self.get_order(str(reference))

    # ── ShopPort: products ──

    def get_products(self, cursor=None, since=None):
        raise NotImplementedError

    def update_product_stock(self, product_id, quantity):
        raise NotImplementedError

    def update_product_price(self, product_id, price, currency):
        raise NotImplementedError

    def update_order_status(self, order_id, status):
        raise NotImplementedError("Temu does not expose a generic order status update; use FulfillmentCapability.")

    # ── capabilities (implemented task by task) ──

    def create_product(self, product):
        raise NotImplementedError

    def delete_product(self, product_id):
        raise NotImplementedError

    def update_product(self, update):
        raise NotImplementedError

    def bulk_update_products(self, updates):
        raise NotImplementedError

    def verify_webhook(self, headers, body, secret=""):
        raise NotImplementedError

    def parse_webhook(self, headers, body):
        raise NotImplementedError

    def register_webhook(self, url, events=None):
        raise NotImplementedError

    def list_webhooks(self):
        raise NotImplementedError

    def attach_invoice(self, order_id, invoice_url, **kwargs):
        raise NotImplementedError

    def get_order_awbs(self, order_id):
        raise NotImplementedError

    def get_awb_pdf(self, awb_id):
        raise NotImplementedError

    def list_carriers(self):
        raise NotImplementedError

    def confirm_shipment(self, order_id, tracking_number, carrier_id, items=None):
        raise NotImplementedError

    def list_shipping_services(self, order_id, warehouse_id):
        raise NotImplementedError

    def create_shipment(self, order_id, shipping_service_id, warehouse_id, items=None, ship_later=False):
        raise NotImplementedError

    def get_shipment_result(self, package_sn):
        raise NotImplementedError

    def confirm_package_shipped(self, package_sn):
        raise NotImplementedError

    def get_order_amounts(self, order_id):
        raise NotImplementedError

    def get_financial_transactions(self, *args, **kwargs):
        raise NotImplementedError

    def get_invoices(self, *args, **kwargs):
        raise NotImplementedError

    def get_returns(self, since, until):
        raise NotImplementedError

