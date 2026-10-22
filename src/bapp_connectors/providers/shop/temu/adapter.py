"""Temu shop adapter."""

from __future__ import annotations

import datetime
import logging
import time
import urllib.parse
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    BulkUpdateCapability,
    Carrier,
    CustomerDetailsCapability,
    FinancialCapability,
    FulfillmentCapability,
    InvoiceAttachmentCapability,
    OrderAmountCapability,
    OrderLookupCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ReturnsCapability,
    ShipmentResult,
    ShippingCapability,
    ShippingService,
    WebhookCapability,
)
from bapp_connectors.core.dto import (
    AWBLabel,
    BulkResult,
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
    ProductUpdate,
)
from bapp_connectors.core.dto.financial import FinancialTransaction
from bapp_connectors.core.dto.returns import ShopReturn
from bapp_connectors.core.dto.webhook import WebhookEvent
from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
    UnsupportedFeatureError,
    ValidationError,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.temu.client import DEFAULT_PAGE_SIZE, TemuApiClient
from bapp_connectors.providers.shop.temu.manifest import manifest
from bapp_connectors.providers.shop.temu.mappers import (
    amounts_from_invoice_detail,
    amounts_from_v2,
    contact_from_shipping_info,
    goods_v3_payload,
    order_from_temu,
    product_from_goods,
    return_from_aftersales,
    sku_ids_from_stock_query,
    transactions_from_statement,
)
from bapp_connectors.providers.shop.temu.models import SITE_CURRENCY, ShippingLabelStatus
from bapp_connectors.providers.shop.temu.webhooks import parse_event

if TYPE_CHECKING:
    from bapp_connectors.core.capabilities import OrderAmounts
    from bapp_connectors.core.dto import Contact

logger = logging.getLogger(__name__)

#: polling of ``temu.finance.mall.bill.task.get`` after a task is created
BILL_POLL_ATTEMPTS = 10
BILL_POLL_SECONDS = 3

#: ``documentType`` of the shipping label PDF in ``bg.logistics.shipment.document.get`` (the doc only
#: shows a placeholder; verify on the test shop and fix here if Temu rejects it)
LABEL_DOCUMENT_TYPE = "SHIPPING_LABEL_PDF"

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

    def _sku_ids(self, product_id: str) -> list[int]:
        pairs = sku_ids_from_stock_query(self.client.sku_stock_query(goods_id=int(product_id)))
        if not pairs:
            raise ValidationError(f"Temu: produsul {product_id} nu are SKU-uri")
        return [sku_id for sku_id, _ in pairs]

    def get_products(self, cursor: str | None = None, since: datetime.datetime | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        filters = {"crtFrom": int(since.timestamp() * 1000)} if since else {}
        data = self.client.list_goods(page_no=page, page_size=DEFAULT_PAGE_SIZE, **filters)
        rows = (data or {}).get("goodsList") or []
        items = [product_from_goods(row) for row in rows]
        has_more = len(rows) == DEFAULT_PAGE_SIZE
        return PaginatedResult(items=items, cursor=str(page + 1) if has_more else None, has_more=has_more,
                               total=(data or {}).get("total"))

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        targets = [{"skuId": sku_id, "stockTarget": int(quantity)} for sku_id in self._sku_ids(product_id)]
        self.client.edit_stock(int(product_id), targets, uuid.uuid4().hex)

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        """Asks Temu for a base-price change (it opens a price order Temu reviews; see the Price Management Guide)."""
        amount = f"{Decimal(price).quantize(Decimal('0.01'))}"
        currency = currency or str(self.config.get("currency") or "RON")
        self.client.change_sku_price(int(product_id), [{
            "reason": "Actualizare preț din BAPP",
            "skuChangePriceBaseDTOList": [{"skuId": sku_id, "newSupplierPrice": {"amount": amount, "currency": currency}}
                                          for sku_id in self._sku_ids(product_id)],
        }])

    def update_order_status(self, order_id, status):
        raise NotImplementedError("Temu does not expose a generic order status update; use FulfillmentCapability.")

    # ── capabilities (implemented task by task) ──

    def create_product(self, product: Product) -> Product:
        result = self.client.add_goods_v3(goods_v3_payload(product, self.config))
        return Product(product_id=str(result.get("goodsId") or ""), sku=product.sku, name=product.name,
                       extra={"status": "draft", "externalGoodsId": result.get("externalGoodsId")})

    def delete_product(self, product_id: str) -> None:
        self.client.delete_goods(int(product_id))

    def update_product(self, update: ProductUpdate) -> None:
        basic: dict = {}
        if update.name is not None:
            basic["goodsName"] = update.name[:500]
        payload: dict = {"goodsId": int(update.product_id)}
        if basic:
            payload["goodsBasic"] = basic
        if update.description is not None:
            payload["goodsDesc"] = update.description[:10000]
        if update.photos:
            payload.setdefault("goodsBasic", {})["goodsCarouselImage"] = [p.url for p in update.photos if p.url][:10]
        if len(payload) > 1:
            self.client.partial_update_goods(payload)
        if update.stock is not None:
            self.update_product_stock(update.product_id, update.stock)
        if update.price is not None:
            self.update_product_price(update.product_id, update.price, update.currency or "")

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        result = BulkResult(total=len(updates))
        for update in updates:
            try:
                if update.stock is not None:
                    self.update_product_stock(update.product_id, update.stock)
                if update.price is not None:
                    self.update_product_price(update.product_id, update.price, update.currency or "")
                result.succeeded += 1
            except (ConnectorError, ValueError) as exc:
                result.failed += 1
                result.errors.append({"product_id": update.product_id, "error": str(exc)})
        return result

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """`secret` is ignored: the scheme is keyed on the app secret this adapter already holds."""
        event = parse_event(headers, body, self.app_secret, self.app_key)
        return bool(event.signature_valid and event.extra.get("app_key_matches"))

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        return parse_event(headers, body, self.app_secret, self.app_key)

    def register_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """Temu has no API for the callback URL (set it in Partner Platform); this activates the events on the shop."""
        permitted = list(events or self.manifest.webhooks.events)
        self.client.update_webhook_subscription(permit=permitted)
        return {"url_note": "Set the callback URL in Partner Platform → Webhook; events activated on the shop.",
                "url": url, "permitted": permitted}

    def list_webhooks(self) -> list[dict]:
        return [{"event": event} for event in self.manifest.webhooks.events]

    # ── InvoiceAttachmentCapability ──

    def attach_invoice(self, order_id: str, invoice_url: str, name: str = "", credit_note: bool = False,
                       currency: str = "", date: str = "", amount: Decimal | None = None) -> bool:
        """Upload the seller's invoice (or credit note) for a parent order; `invoice_url` must be public."""
        if not name:
            name = urllib.parse.urlparse(invoice_url).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        fields: dict = {
            "parentOrderSn": order_id,
            "invoiceDirection": 2 if credit_note else 1,
            "invoiceName": name[:200],
            "recipientType": 1,
            "fileUrl": invoice_url,
        }
        if currency:
            fields["invoiceCurrency"] = currency
        if date:
            fields["invoiceDate"] = date
        if amount is not None:
            fields["invoiceAmount"] = float(amount)
        result = self.client.upload_invoice(**fields)
        return bool(result.get("success", True)) if isinstance(result, dict) else True

    # ── FulfillmentCapability / ShippingCapability ──

    def _order_send_info(self, order_id: str, items: list[str] | None = None) -> list[dict]:
        """``orderSendInfoList`` for a parent order: every child line, or only ``items`` (orderSn list)."""
        detail = self.client.order_detail(order_id)
        wanted = set(items or [])
        lines = [
            {"orderSn": str(line.get("orderSn") or ""), "parentOrderSn": order_id, "goodsId": line.get("goodsId"),
             "skuId": line.get("skuId"), "quantity": int(line.get("quantity") or 0)}
            for line in (detail.get("orderList") or [])
            if not wanted or str(line.get("orderSn") or "") in wanted
        ]
        if not lines:
            raise ValidationError(f"Temu: comanda {order_id} nu are linii de expediat")
        return lines

    def _region_id(self) -> int | None:
        """The mall's Temu region (167 = RO site family); from config, else from the token info (cached)."""
        configured = self.config.get("region_id")
        if configured not in (None, ""):
            return int(configured)
        if getattr(self, "_cached_region_id", None) is None:
            try:
                self._cached_region_id = int(self.client.token_info().get("regionId") or 0) or None
            except ConnectorError:
                self._cached_region_id = None
        return self._cached_region_id

    def list_carriers(self) -> list[Carrier]:
        # without regionId the test shop answers 7000000 BUSINESS_SERVICE_ERROR
        raw = self.client.list_carriers(region_id=self._region_id())
        rows = raw if isinstance(raw, list) else (raw.get("logisticsServiceProviderList") or raw.get("list") or [])
        return [
            Carrier(carrier_id=str(row.get("logisticsServiceProviderId") or ""),
                    name=str(row.get("logisticsServiceProviderName") or row.get("logisticsBrandName") or ""), extra=row)
            for row in rows
        ]

    def confirm_shipment(self, order_id: str, tracking_number: str, carrier_id: str, items: list[str] | None = None) -> None:
        self.client.confirm_shipment_v2({
            "sendType": 0,
            "sendRequestList": [{"trackingNumber": tracking_number, "carrierId": str(carrier_id),
                                 "orderSendInfoList": self._order_send_info(order_id, items)}],
        })

    def _services(self, order_id: str, warehouse_id: str, items: list[str] | None = None) -> list[ShippingService]:
        lines = self._order_send_info(order_id, items)
        data = self.client.shipping_services({
            "warehouseId": warehouse_id,
            "shipOrderInfoList": [{"orderSn": line["orderSn"], "parentOrderSn": order_id, "quantity": line["quantity"]}
                                  for line in lines],
        })
        services = []
        for channel in data.get("onlineChannelDtoList") or []:
            services.append(ShippingService(
                service_id=str(channel.get("channelId") or ""),
                name=str(channel.get("shippingCompanyName") or channel.get("channelId") or ""),
                carrier_id=str(channel.get("shipCompanyId") or ""),
                currency=str(channel.get("estimatedCurrencyCode") or ""),
                extra=channel,
            ))
        return services

    def list_shipping_services(self, order_id: str, warehouse_id: str) -> list[ShippingService]:
        return self._services(order_id, warehouse_id)

    def create_shipment(self, order_id: str, shipping_service_id: str, warehouse_id: str,
                        items: list[str] | None = None, ship_later: bool = False) -> str:
        service = next((s for s in self._services(order_id, warehouse_id, items) if s.service_id == str(shipping_service_id)), None)
        if service is None:
            raise ValidationError(f"Temu: serviciul de transport {shipping_service_id} nu e disponibil pentru comanda {order_id}")
        request: dict = {
            "channelId": int(service.service_id),
            "warehouseId": warehouse_id,
            "orderSendInfoList": self._order_send_info(order_id, items),
        }
        if service.carrier_id:
            request["shipCompanyId"] = int(service.carrier_id)
        if service.extra.get("shipLogisticsType"):
            request["shipLogisticsType"] = service.extra["shipLogisticsType"]
        result = self.client.create_shipment({"sendType": 0, "sendRequestList": [request], "shipLater": bool(ship_later)})
        packages = result.get("packageSnList") or []
        if not packages:
            raise ProviderError(f"Temu: nu a întors packageSn pentru comanda {order_id}: {result.get('warningMessage')}")
        return str(packages[0])

    @staticmethod
    def _shipment_result_from(row: dict, package_sn: str) -> ShipmentResult:
        try:
            status_code = ShippingLabelStatus(int(row.get("shippingLabelStatus")))
        except (TypeError, ValueError):
            status_code = ShippingLabelStatus.IN_APPLICATION
        status = {ShippingLabelStatus.SUCCESS: "success", ShippingLabelStatus.FAILED: "failed"}.get(status_code, "pending")
        companies = row.get("interlineShipCompanyList") or []
        carrier = str((companies[0] or {}).get("shippingCompanyName") or "") if companies else ""
        return ShipmentResult(
            package_sn=str(row.get("packageSn") or package_sn),
            status=status,
            tracking_number=str(row.get("trackingNumber") or ""),
            carrier=carrier,
            error=str(row.get("failReasonText") or "") if status == "failed" else "",
            extra={k: v for k, v in row.items() if k not in ("interlineShipCompanyList",)},
        )

    def get_shipment_result(self, package_sn: str) -> ShipmentResult:
        rows = self.client.shipment_result([package_sn]).get("packageInfoResultList") or []
        row = next((r for r in rows if str(r.get("packageSn") or "") == package_sn), rows[0] if rows else None)
        if row is None:
            return ShipmentResult(package_sn=package_sn, status="pending")
        return self._shipment_result_from(row, package_sn)

    def confirm_package_shipped(self, package_sn: str) -> None:
        self.client.confirm_shipped_package([{"packageSn": package_sn}])

    def get_order_awbs(self, order_id: str) -> list[AWBLabel]:
        detail = self.client.order_detail(order_id)
        package_sns = []
        for line in detail.get("orderList") or []:
            for package in line.get("packageSnInfo") or []:
                sn = str(package.get("packageSn") or "")
                if sn and package.get("callSuccess", True) and sn not in package_sns:
                    package_sns.append(sn)
        if not package_sns:
            return []
        rows = {str(r.get("packageSn") or ""): r for r in self.client.shipment_result(package_sns).get("packageInfoResultList") or []}
        labels = []
        for sn in package_sns:
            result = self._shipment_result_from(rows[sn], sn) if sn in rows else ShipmentResult(package_sn=sn, status="pending")
            labels.append(AWBLabel(tracking_number=result.tracking_number or sn,
                                   extra={"package_sn": sn, "status": result.status, "carrier": result.carrier}))
        return labels

    def get_awb_pdf(self, awb_id: str) -> bytes:
        """`awb_id` is the package sn; the label URL is signed and expires after 10 minutes."""
        data = self.client.shipment_document([awb_id], LABEL_DOCUMENT_TYPE)
        urls = data.get("shippingLabelUrlList") or []
        url = next((u.get("url") for u in urls if str(u.get("packageSn") or awb_id) == awb_id and u.get("url")), None)
        if not url:
            raise ProviderError(f"Temu: nu există etichetă pentru pachetul {awb_id}: {data.get('warningMessage')}")
        return self.client.download_signed(str(url))

    # ── OrderAmountCapability ──

    def get_order_amounts(self, order_id: str) -> OrderAmounts:
        """Consumer prices + seller settlement; falls back to the self-billing invoice content when
        the token lacks the amount scope (3000032) or the API is unsupported."""
        try:
            return amounts_from_v2(self.client.order_amounts_v2(order_id), order_id)
        except (AuthenticationError, UnsupportedFeatureError) as first:
            data = self.client.invoice_detail(order_id)
            if not (data or {}).get("invoiceDetailInfoList"):
                raise first
            return amounts_from_invoice_detail(data, order_id)

    # ── FinancialCapability ──

    _sleep = staticmethod(time.sleep)

    def _await_bill_file(self, task_id: str) -> str:
        """Poll the bill task until it is terminal; returns the signed file URL."""
        for attempt in range(BILL_POLL_ATTEMPTS):
            if attempt:
                self._sleep(BILL_POLL_SECONDS)
            task = self.client.get_bill_task(task_id)
            status = str(task.get("status") or "").upper()
            if task.get("fileUrl"):
                return str(task["fileUrl"])
            if "FAIL" in status or "ERROR" in status or task.get("errorCode"):
                raise ProviderError(f"Temu bill task {task_id} failed: {task.get('errorMessage') or status}")
        raise ProviderError(f"Temu bill task {task_id} not ready after {BILL_POLL_ATTEMPTS} polls", retryable=True)

    def get_financial_transactions(self, start_date: datetime.datetime, end_date: datetime.datetime,
                                   transaction_type: str | None = None, cursor: str | None = None) -> PaginatedResult[FinancialTransaction]:
        file_type = transaction_type or "STATEMENT_REPORT"
        task = self.client.create_bill_task(file_type, int(start_date.timestamp() * 1000), int(end_date.timestamp() * 1000))
        task_id = str(task.get("taskId") or "")
        if not task_id:
            raise ProviderError(f"Temu bill task not created: {task}")
        url = self._await_bill_file(task_id)
        content = self.client.download_signed(url)
        rows = transactions_from_statement(content, str(self.config.get("currency") or ""))
        return PaginatedResult(items=rows, cursor=None, has_more=False, total=len(rows))

    def get_invoices(self, start_date=None, end_date=None, category=None, cursor=None):
        raise NotImplementedError("Temu does not expose its commission invoices through the API")

    # ── ReturnsCapability ──

    def get_returns(self, since: datetime.datetime, until: datetime.datetime) -> list[ShopReturn]:
        start, end = int(since.timestamp()), int(until.timestamp())
        page, returns = 1, []
        while True:
            data = self.client.list_aftersales(page, DEFAULT_PAGE_SIZE, start, end)
            rows = data.get("data") or []
            for row in rows:
                sn = str(row.get("parentAfterSalesSn") or "")
                detail = None
                try:
                    detail = self.client.aftersales_detail(sn, str(row.get("parentOrderSn") or ""))
                except ConnectorError as exc:
                    logger.warning("temu: after-sales detail %s failed: %s", sn, exc)
                    returns.append(return_from_aftersales(row, None).model_copy(update={"raw": {"item": row, "detail": {}, "detail_error": str(exc)}}))
                    continue
                returns.append(return_from_aftersales(row, detail))
            total = data.get("total")
            if not rows or (total is not None and page * DEFAULT_PAGE_SIZE >= int(total)):
                break
            page += 1
        return returns

    def resolve_return_awb(self, awb_ref: str) -> str:
        return awb_ref

