"""Raw Temu Open API client: one signed JSON POST per call to the regional router.

The registry injects a ``ResilientHttpClient`` built from the manifest's placeholder ``base_url``
with no auth; this client therefore builds the absolute router URL per call and signs the body
itself, using the injected client only for retry policy, rate limiting and logging.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ConnectorError, ProviderError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.providers.shop.temu.errors import RATE_LIMIT_CODES, TRANSIENT_CODES, classify_temu_error
from bapp_connectors.providers.shop.temu.signing import sign_params, signed_document_headers

ROUTERS = {
    "eu": "https://openapi-b-eu.temu.com/openapi/router",
    "us": "https://openapi-b-us.temu.com/openapi/router",
    "global": "https://openapi-b-global.temu.com/openapi/router",
}
DEFAULT_PAGE_SIZE = 50


# bg.logistics.shippingservices.get request fields an agent may send in `payload`.
AI_SHIPPING_SERVICES_KEYS = (
    "warehouseId", "shipOrderInfoList", "weight", "weightUnit", "length", "width", "height", "dimensionUnit",
)


class TemuApiClient:
    #: pauses (s) before retrying an answer Temu rate-limited: the request was not executed, so writes retry too
    RATE_LIMIT_BACKOFF = (1, 2, 4)
    #: pauses (s) before retrying a transient service error; reads only (a write may have gone through)
    TRANSIENT_BACKOFF = (1, 3)
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        access_token: str,
        region: str = "eu",
        http_client: ResilientHttpClient | None = None,
    ):
        if region not in ROUTERS:
            raise ValueError(f"Unknown Temu region {region!r}; expected one of {sorted(ROUTERS)}")
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.region = region
        self.base_url = ROUTERS[region]
        self.http = http_client or ResilientHttpClient(base_url=self.base_url, provider_name="temu")

    # ------------------------------------------------------------------ core
    def call(self, api_type: str, retry: bool = True, log_body: bool = False, **params: Any) -> Any:
        """One signed POST. `log_body=True` keeps request+response in the host's execution log: used only
        on writes (the answer is what we need when something goes wrong); never on calls that return the
        buyer's personal data (shipping info, decrypted shipping info)."""
        rate_waits, transient_waits = list(self.RATE_LIMIT_BACKOFF), list(self.TRANSIENT_BACKOFF) if retry else []
        while True:
            response = self._post(api_type, retry, log_body, params)
            if response.get("success"):
                return response.get("result")
            code = int(response.get("errorCode") or 0)
            if code in RATE_LIMIT_CODES and rate_waits:
                time.sleep(rate_waits.pop(0))
                continue
            if code in TRANSIENT_CODES and transient_waits:
                time.sleep(transient_waits.pop(0))
                continue
            raise classify_temu_error(code, str(response.get("errorMsg") or ""), str(response.get("requestId") or ""), api_type)

    def _post(self, api_type: str, retry: bool, log_body: bool, params: dict) -> dict:
        """One signed POST (a fresh timestamp and signature per attempt); the raw answer dict."""
        # The envelope goes last: a business parameter (a filter, a payload key) can never
        # replace `type` and turn a read into another API call, nor swap the credentials.
        body = {
            **{k: v for k, v in params.items() if v is not None},
            "type": api_type,
            "app_key": self.app_key,
            "access_token": self.access_token,
            "timestamp": str(int(time.time())),
            "sign_method": "md5",
            "data_type": "JSON",
        }
        body["sign"] = sign_params(self.app_secret, body)
        kwargs: dict = {"json": body, "headers": {"Content-Type": "application/json"}}
        if log_body:
            kwargs["log_body"] = True
        if not retry:
            kwargs["retry"] = False
        try:
            response = self.http.call("POST", self.base_url, **kwargs)
        except ConnectorError:
            raise
        except requests.RequestException as exc:
            raise ProviderError(f"Temu {api_type}: transport error: {exc}", retryable=True) from exc
        if not isinstance(response, dict):
            raise ProviderError(f"Temu {api_type}: unexpected response {str(response)[:200]!r}")
        return response

    def download_signed(self, url: str) -> bytes:
        """GET a signed document URL (label PDF, report file) with the ``toa-*`` headers."""
        headers = signed_document_headers(self.app_key, self.app_secret, self.access_token)
        try:
            response = self.http.call("GET", url, direct_response=True, headers=headers)
        except ConnectorError:
            raise
        except requests.RequestException as exc:
            raise ProviderError(f"Temu document download: transport error: {exc}", retryable=True) from exc
        if not getattr(response, "ok", False):
            status = getattr(response, "status_code", None)
            raise ProviderError(f"Temu document download failed with HTTP {status} (signed URL expired or refused)",
                                status_code=status, retryable=status in (429, 500, 502, 503, 504))
        return response.content

    # ------------------------------------------------------------ authorization
    @ai_method("read", "The access token's details (scopes, expiry, mall), in one call.")
    def token_info(self) -> dict:
        return self.call("bg.open.accesstoken.info.get") or {}

    @ai_method("read", "The mall's settlement status, in one call.")
    def settle_status(self) -> dict:
        return self.call("temu.local.mall.settlestatus.get") or {}

    @ai_method("read", "The mall's warehouses, in one call.")
    def warehouses(self) -> list:
        return (self.call("bg.logistics.warehouse.list.get") or {}).get("warehouseList") or []

    # ------------------------------------------------------------------ orders
    @ai_method(
        "read",
        "Parent orders, one page per call (page_number from 1, page_size), filtered by status, update time (s) or order numbers.",
    )
    def list_orders(
        self,
        page_number: int,
        page_size: int = DEFAULT_PAGE_SIZE,
        parent_order_status: int = 0,
        update_at_start: int | None = None,
        update_at_end: int | None = None,
        parent_order_sn_list: list[str] | None = None,
    ) -> dict:
        return self.call(
            "bg.order.list.v2.get",
            pageNumber=page_number,
            pageSize=page_size,
            parentOrderStatus=parent_order_status,
            updateAtStart=update_at_start,
            updateAtEnd=update_at_end,
            parentOrderSnList=parent_order_sn_list,
        ) or {}

    @ai_method("read", "One parent order with its items.")
    def order_detail(self, parent_order_sn: str) -> dict:
        return self.call("bg.order.detail.v2.get", parentOrderSn=parent_order_sn) or {}

    @ai_method("read", "The masked shipping data of one parent order.")
    def shipping_info(self, parent_order_sn: str) -> dict:
        return self.call("bg.order.shippinginfo.v2.get", parentOrderSn=parent_order_sn) or {}

    def decrypt_shipping_info(self, parent_order_sn: str) -> dict:
        return self.call("bg.order.decryptshippinginfo.get", parentOrderSn=parent_order_sn) or {}

    @ai_method("read", "The money amounts of one parent order (minor units).")
    def order_amounts_v2(self, parent_order_sn: str) -> dict:
        return self.call("temu.order.amount.v2.query", parentOrderSn=parent_order_sn) or {}

    # ---------------------------------------------------------------- invoices
    @ai_method("read", "The tax invoice status of one parent order.")
    def invoice_detail(self, parent_order_sn: str) -> dict:
        return self.call("temu.pay.tax.invoice.detail.query", parentOrderSn=parent_order_sn) or {}

    def upload_invoice(self, **fields: Any) -> dict:
        return self.call("temu.pay.tax.merchant.upload.invoice", retry=False, log_body=True, **fields) or {}

    # ------------------------------------------------------------------- goods
    @ai_method(
        "read",
        "Goods, one page per call (page_no from 1, page_size), optionally created from crtFrom (ms) or by statusFilterType.",
        extra={
            "crtFrom": "scalar",
            "statusFilterType": "scalar",
            "goodsSearchType": "scalar",
        },
    )
    def list_goods(self, page_no: int, page_size: int = DEFAULT_PAGE_SIZE, **filters: Any) -> dict | None:
        # statusFilterType 0 = every status; 1 (on sale) answers `result: null` on a shop with drafts only
        params = {"goodsSearchType": 1, "statusFilterType": 0, **filters}
        return self.call("bg.local.goods.list.query", pageNo=page_no, pageSize=page_size, **params)

    @ai_method("read", "One goods with its SKUs.")
    def goods_detail(self, goods_id: int) -> dict:
        return self.call("bg.local.goods.detail.query", goodsId=goods_id) or {}

    @ai_method("write", "Create a goods.")
    def add_goods_v3(self, payload: dict) -> dict:
        return self.call("temu.local.goods.v3.add", retry=False, log_body=True, **payload) or {}

    @ai_method("write", "Delete a goods.")
    def delete_goods(self, goods_id: int) -> dict:
        return self.call("temu.local.goods.delete", retry=False, log_body=True, goodsId=goods_id) or {}

    @ai_method("write", "Update some fields of a goods.")
    def partial_update_goods(self, payload: dict) -> dict:
        return self.call("bg.local.goods.partial.update", retry=False, log_body=True, **payload) or {}

    @ai_method("write", "Set the stock of SKUs of a goods.")
    def edit_stock(self, goods_id: int, sku_stock_target_list: list[dict], request_unique_key: str) -> dict:
        return self.call(
            "bg.local.goods.stock.edit",
            retry=False,
            log_body=True,
            goodsId=goods_id,
            skuStockTargetList=sku_stock_target_list,
            requestUniqueKey=request_unique_key,
        ) or {}

    @ai_method("read", "The stock of a goods' SKUs or of SKUs by seller SKU code.")
    def sku_stock_query(self, goods_id: int | None = None, out_sku_sn_list: list[str] | None = None) -> dict:
        return self.call("temu.local.goods.sku.stock.query", goodsId=goods_id, outSkuSnList=out_sku_sn_list) or {}

    @ai_method("write", "Change the price of SKUs of a goods.")
    def change_sku_price(self, goods_id: int, change_sku_price_dto_list: list[dict]) -> dict:
        return self.call(
            "bg.local.goods.priceorder.change.sku.price",
            retry=False,
            log_body=True,
            goodsId=goods_id,
            changeSkuPriceDTOList=change_sku_price_dto_list,
        ) or {}

    # --------------------------------------------------------------- logistics
    @ai_method("read", "The carriers available, optionally for one region.")
    def list_carriers(self, region_id: int | None = None) -> dict:
        return self.call("bg.logistics.companies.get", regionId=region_id) or {}

    @ai_method("write", "Confirm the shipment of an order with the seller's own courier.")
    def confirm_shipment_v2(self, payload: dict) -> dict:
        return self.call("bg.logistics.shipment.v2.confirm", retry=False, log_body=True, **payload) or {}

    @ai_method(
        "read",
        "The Temu shipping services offered for a package, without buying one.",
        allowed_keys={"payload": AI_SHIPPING_SERVICES_KEYS},
    )
    def shipping_services(self, payload: dict) -> dict:
        # `retry`/`log_body` are call() options, never request fields
        fields = {k: v for k, v in payload.items() if k not in ("retry", "log_body")}
        return self.call("bg.logistics.shippingservices.get", **fields) or {}

    @ai_method("write", "Buy a Temu shipping label for a package.")
    def create_shipment(self, payload: dict) -> dict:
        return self.call("bg.logistics.shipment.create", retry=False, log_body=True, **payload) or {}

    @ai_method("read", "The result of earlier shipment creations, by package numbers.")
    def shipment_result(self, package_sn_list: list[str]) -> dict:
        return self.call("bg.logistics.shipment.result.get", packageSnList=package_sn_list) or {}

    @ai_method("read", "The download links of shipping documents (labels) for packages.")
    def shipment_document(self, package_sn_list: list[str], document_type: str) -> dict:
        return self.call("bg.logistics.shipment.document.get", packageSnList=package_sn_list, documentType=document_type) or {}

    @ai_method("write", "Confirm that packages were handed to the courier.")
    def confirm_shipped_package(self, package_send_info_list: list[dict]) -> dict:
        return self.call("bg.logistics.shipped.package.confirm", retry=False, log_body=True, packageSendInfoList=package_send_info_list) or {}

    # ----------------------------------------------------------------- finance
    @ai_method("write", "Start a bill export task for a time range (creates a task at Temu).")
    def create_bill_task(self, file_type: str, start_ms: int, end_ms: int) -> dict:
        return self.call(
            "temu.finance.mall.bill.task.create", retry=False, log_body=True, fileType=file_type, startTime=start_ms, endTime=end_ms
        ) or {}

    @ai_method("read", "The status and file link of a bill export task.")
    def get_bill_task(self, task_id: str) -> dict:
        return self.call("temu.finance.mall.bill.task.get", taskId=task_id) or {}

    # -------------------------------------------------------------- aftersales
    @ai_method("read", "After-sales cases created in a time range (ms), one page per call (page_no, page_size).")
    def list_aftersales(self, page_no: int, page_size: int, create_at_start: int, create_at_end: int) -> dict:
        return self.call(
            "bg.aftersales.parentaftersales.list.get",
            pageNo=page_no,
            pageSize=page_size,
            createAtStart=create_at_start,
            createAtEnd=create_at_end,
        ) or {}

    @ai_method("read", "One after-sales case, by its number and its parent order number.")
    def aftersales_detail(self, parent_after_sales_sn: str, parent_order_sn: str) -> dict:
        # both ids are required: without parentOrderSn Temu answers 130010001 "parameter is illegal"
        return self.call("temu.aftersales.parentaftersales.detail.get", parentAfterSalesSn=parent_after_sales_sn,
                         parentOrderSn=parent_order_sn) or {}

    @ai_method("read", "Cancellation requests, one page per call (page_no, page_size).")
    def list_cancellations(self, page_no: int, page_size: int) -> dict:
        return self.call("bg.aftersales.cancel.list.get", pageNo=page_no, pageSize=page_size) or {}

    # ---------------------------------------------------------------- webhooks
    def update_webhook_subscription(self, permit: list[str] | None = None, cancel: list[str] | None = None) -> dict:
        return self.call("bg.tmc.message.update", retry=False, log_body=True, permitEventCodeList=permit, cancelEventCodeList=cancel) or {}
