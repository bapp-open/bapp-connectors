"""Raw Temu Open API client: one signed JSON POST per call to the regional router.

The registry injects a ``ResilientHttpClient`` built from the manifest's placeholder ``base_url``
with no auth; this client therefore builds the absolute router URL per call and signs the body
itself, using the injected client only for retry policy, rate limiting and logging.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from bapp_connectors.core.errors import ConnectorError, ProviderError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.providers.shop.temu.errors import classify_temu_error
from bapp_connectors.providers.shop.temu.signing import sign_params, signed_document_headers

ROUTERS = {
    "eu": "https://openapi-b-eu.temu.com/openapi/router",
    "us": "https://openapi-b-us.temu.com/openapi/router",
    "global": "https://openapi-b-global.temu.com/openapi/router",
}
DEFAULT_PAGE_SIZE = 50


class TemuApiClient:
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
    def call(self, api_type: str, retry: bool = True, **params: Any) -> Any:
        body = {
            "type": api_type,
            "app_key": self.app_key,
            "access_token": self.access_token,
            "timestamp": str(int(time.time())),
            "sign_method": "md5",
            "data_type": "JSON",
            **{k: v for k, v in params.items() if v is not None},
        }
        body["sign"] = sign_params(self.app_secret, body)
        kwargs: dict = {"json": body, "headers": {"Content-Type": "application/json"}, "log_body": True}
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
        if not response.get("success"):
            raise classify_temu_error(
                int(response.get("errorCode") or 0),
                str(response.get("errorMsg") or ""),
                str(response.get("requestId") or ""),
                api_type,
            )
        return response.get("result")

    def download_signed(self, url: str) -> bytes:
        """GET a signed document URL (label PDF, report file) with the ``toa-*`` headers."""
        headers = signed_document_headers(self.app_key, self.app_secret, self.access_token)
        try:
            response = self.http.call("GET", url, direct_response=True, headers=headers)
        except ConnectorError:
            raise
        except requests.RequestException as exc:
            raise ProviderError(f"Temu document download: transport error: {exc}", retryable=True) from exc
        return response.content

    # ------------------------------------------------------------ authorization
    def token_info(self) -> dict:
        return self.call("bg.open.accesstoken.info.get") or {}

    def settle_status(self) -> dict:
        return self.call("temu.local.mall.settlestatus.get") or {}

    def warehouses(self) -> list:
        return (self.call("bg.logistics.warehouse.list.get") or {}).get("warehouseList") or []

    # ------------------------------------------------------------------ orders
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

    def order_detail(self, parent_order_sn: str) -> dict:
        return self.call("bg.order.detail.v2.get", parentOrderSn=parent_order_sn) or {}

    def shipping_info(self, parent_order_sn: str) -> dict:
        return self.call("bg.order.shippinginfo.v2.get", parentOrderSn=parent_order_sn) or {}

    def decrypt_shipping_info(self, parent_order_sn: str) -> dict:
        return self.call("bg.order.decryptshippinginfo.get", parentOrderSn=parent_order_sn) or {}

    def order_amounts_v2(self, parent_order_sn: str) -> dict:
        return self.call("temu.order.amount.v2.query", parentOrderSn=parent_order_sn) or {}

    # ---------------------------------------------------------------- invoices
    def invoice_detail(self, parent_order_sn: str) -> dict:
        return self.call("temu.pay.tax.invoice.detail.query", parentOrderSn=parent_order_sn) or {}

    def upload_invoice(self, **fields: Any) -> dict:
        return self.call("temu.pay.tax.merchant.upload.invoice", retry=False, **fields) or {}

    # ------------------------------------------------------------------- goods
    def list_goods(self, page_no: int, page_size: int = DEFAULT_PAGE_SIZE, **filters: Any) -> dict | None:
        params = {"goodsSearchType": 1, "statusFilterType": 1, **filters}
        return self.call("bg.local.goods.list.query", pageNo=page_no, pageSize=page_size, **params)

    def goods_detail(self, goods_id: int) -> dict:
        return self.call("bg.local.goods.detail.query", goodsId=goods_id) or {}

    def add_goods_v3(self, payload: dict) -> dict:
        return self.call("temu.local.goods.v3.add", retry=False, **payload) or {}

    def delete_goods(self, goods_id: int) -> dict:
        return self.call("temu.local.goods.delete", retry=False, goodsId=goods_id) or {}

    def partial_update_goods(self, payload: dict) -> dict:
        return self.call("bg.local.goods.partial.update", retry=False, **payload) or {}

    def edit_stock(self, goods_id: int, sku_stock_target_list: list[dict], request_unique_key: str) -> dict:
        return self.call(
            "bg.local.goods.stock.edit",
            retry=False,
            goodsId=goods_id,
            skuStockTargetList=sku_stock_target_list,
            requestUniqueKey=request_unique_key,
        ) or {}

    def sku_stock_query(self, goods_id: int | None = None, out_sku_sn_list: list[str] | None = None) -> dict:
        return self.call("temu.local.goods.sku.stock.query", goodsId=goods_id, outSkuSnList=out_sku_sn_list) or {}

    def change_sku_price(self, goods_id: int, change_sku_price_dto_list: list[dict]) -> dict:
        return self.call(
            "bg.local.goods.priceorder.change.sku.price",
            retry=False,
            goodsId=goods_id,
            changeSkuPriceDTOList=change_sku_price_dto_list,
        ) or {}

    # --------------------------------------------------------------- logistics
    def list_carriers(self, region_id: int | None = None) -> dict:
        return self.call("bg.logistics.companies.get", regionId=region_id) or {}

    def confirm_shipment_v2(self, payload: dict) -> dict:
        return self.call("bg.logistics.shipment.v2.confirm", retry=False, **payload) or {}

    def shipping_services(self, payload: dict) -> dict:
        return self.call("bg.logistics.shippingservices.get", **payload) or {}

    def create_shipment(self, payload: dict) -> dict:
        return self.call("bg.logistics.shipment.create", retry=False, **payload) or {}

    def shipment_result(self, package_sn_list: list[str]) -> dict:
        return self.call("bg.logistics.shipment.result.get", packageSnList=package_sn_list) or {}

    def shipment_document(self, package_sn_list: list[str], document_type: str) -> dict:
        return self.call("bg.logistics.shipment.document.get", packageSnList=package_sn_list, documentType=document_type) or {}

    def confirm_shipped_package(self, package_send_info_list: list[dict]) -> dict:
        return self.call("bg.logistics.shipped.package.confirm", retry=False, packageSendInfoList=package_send_info_list) or {}

    # ----------------------------------------------------------------- finance
    def create_bill_task(self, file_type: str, start_ms: int, end_ms: int) -> dict:
        return self.call(
            "temu.finance.mall.bill.task.create", retry=False, fileType=file_type, startTime=start_ms, endTime=end_ms
        ) or {}

    def get_bill_task(self, task_id: str) -> dict:
        return self.call("temu.finance.mall.bill.task.get", taskId=task_id) or {}

    # -------------------------------------------------------------- aftersales
    def list_aftersales(self, page_no: int, page_size: int, create_at_start: int, create_at_end: int) -> dict:
        return self.call(
            "bg.aftersales.parentaftersales.list.get",
            pageNo=page_no,
            pageSize=page_size,
            createAtStart=create_at_start,
            createAtEnd=create_at_end,
        ) or {}

    def aftersales_detail(self, parent_after_sales_sn: str) -> dict:
        return self.call("temu.aftersales.parentaftersales.detail.get", parentAfterSalesSn=parent_after_sales_sn) or {}

    def list_cancellations(self, page_no: int, page_size: int) -> dict:
        return self.call("bg.aftersales.cancel.list.get", pageNo=page_no, pageSize=page_size) or {}

    # ---------------------------------------------------------------- webhooks
    def update_webhook_subscription(self, permit: list[str] | None = None, cancel: list[str] | None = None) -> dict:
        return self.call("bg.tmc.message.update", retry=False, permitEventCodeList=permit, cancelEventCodeList=cancel) or {}
