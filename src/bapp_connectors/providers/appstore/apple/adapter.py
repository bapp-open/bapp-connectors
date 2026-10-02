"""Adapterul Apple App Store — AppStorePort + FinancialCapability + WebhookCapability."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStorePlatform,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    ConnectionTestResult,
    FinancialTransaction,
    PaginatedResult,
    Subscription,
    WebhookEvent,
)
from bapp_connectors.core.errors import AuthenticationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.reports import daily_page, gunzip_tsv_rows
from bapp_connectors.providers.appstore.apple.auth import AppleJwtAuth
from bapp_connectors.providers.appstore.apple.client import (
    SERVER_API_BASE_URL,
    SERVER_API_SANDBOX_BASE_URL,
    AppleApiClient,
    AppleServerApiClient,
)
from bapp_connectors.providers.appstore.apple.fiscal_calendar import fiscal_periods_between
from bapp_connectors.providers.appstore.apple.manifest import manifest
from bapp_connectors.providers.appstore.apple.mappers import (
    app_from_apple,
    refund_from_sale,
    review_from_apple,
    sale_from_sales_row,
    transaction_from_finance_row,
)


class AppleAppStoreAdapter(AppStorePort, FinancialCapability, WebhookCapability):
    manifest = manifest

    def __init__(
        self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs
    ):
        self.credentials = credentials
        self.config = config or {}
        auth = AppleJwtAuth(
            credentials.get("issuer_id", ""),
            credentials.get("key_id", ""),
            credentials.get("private_key", ""),
        )
        if http_client is None:
            http_client = ResilientHttpClient(base_url=self.manifest.base_url, auth=auth, provider_name="apple")
        else:
            http_client.auth = auth  # registry-ul trimite NoAuth pentru AuthStrategy.CUSTOM
        self.http = http_client
        self.client = AppleApiClient(http_client=http_client, vendor_number=credentials.get("vendor_number", ""))
        self._server_client: AppleServerApiClient | None = None

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            ok = self.client.test_auth()
            return ConnectionTestResult(success=ok, message="Connection successful" if ok else "Authentication failed")
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))

    # ── AppStorePort ──

    def list_apps(self) -> list[AppStoreApp]:
        try:
            return [app_from_apple(item) for item in self.client.list_apps()]
        except AuthenticationError:
            # O cheie cu doar rolul Finance poate sa nu vada GET /v1/apps: cadem pe aplicatiile din raportul de ieri.
            yesterday = date.today() - timedelta(days=1)
            seen: dict[str, AppStoreApp] = {}
            for row in self._sales_rows(yesterday):
                app_id = row.get("Apple Identifier", "")
                if app_id and app_id not in seen:
                    seen[app_id] = AppStoreApp(
                        app_id=app_id,
                        platform=AppStorePlatform.APPLE,
                        name=row.get("Title", ""),
                        bundle_id=row.get("Parent Identifier", "") or row.get("SKU", ""),
                    )
            return list(seen.values())

    def _sales_rows(self, day: date) -> list[dict]:
        content = self.client.download_sales_report(day.isoformat())
        return gunzip_tsv_rows(content) if content else []

    def get_sales(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreSale]:
        day, next_cursor = daily_page(start, end, cursor)
        include_free = self.config.get("include_free_apps", True)
        items = []
        for row in self._sales_rows(day):
            sale = sale_from_sales_row(row, day)
            if sale is None:
                continue
            if not include_free and sale.proceeds_total == 0 and not sale.is_refund:
                continue
            items.append(sale)
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def list_refunds(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreRefund]:
        day, next_cursor = daily_page(start, end, cursor)
        items = []
        for row in self._sales_rows(day):
            sale = sale_from_sales_row(row, day)
            if sale is not None and sale.is_refund:
                items.append(refund_from_sale(sale))
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def list_reviews(
        self, app_id: str, since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[AppStoreReview]:
        page = self.client.list_reviews(app_id, next_url=cursor)
        responses = {
            item.get("id", ""): item
            for item in page.get("included", [])
            if item.get("type") == "customerReviewResponses"
        }
        items = [review_from_apple(item, responses, app_id) for item in page.get("data", [])]
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            items = [r for r in items if r.created_at is None or r.created_at >= since]
        next_url = (page.get("links") or {}).get("next")
        return PaginatedResult(items=items, cursor=next_url, has_more=bool(next_url))

    def reply_to_review(self, app_id: str, review_id: str, text: str) -> AppStoreReview:
        response = self.client.create_review_response(review_id, text)
        data = response.get("data") or {}
        responses = {data.get("id", ""): data}
        review = {
            "id": review_id,
            "attributes": {},
            "relationships": {"response": {"data": {"type": "customerReviewResponses", "id": data.get("id", "")}}},
        }
        return review_from_apple(review, responses, app_id)

    def _server_api(self) -> AppleServerApiClient:
        if self._server_client is None:
            if not (
                self.credentials.get("iap_key_id")
                and self.credentials.get("iap_private_key")
                and self.credentials.get("bundle_id")
            ):
                raise NotImplementedError(
                    "Apple: cheia In-App Purchase (iap_key_id, iap_private_key) si bundle_id lipsesc; abonamentele cer App Store Server API"
                )
            auth = AppleJwtAuth(
                self.credentials.get("issuer_id", ""),
                self.credentials["iap_key_id"],
                self.credentials["iap_private_key"],
                bundle_id=self.credentials["bundle_id"],
            )
            base = (
                SERVER_API_SANDBOX_BASE_URL
                if self.config.get("server_api_environment") == "sandbox"
                else SERVER_API_BASE_URL
            )
            self._server_client = AppleServerApiClient(
                ResilientHttpClient(base_url=base, auth=auth, provider_name="apple-server-api")
            )
        return self._server_client

    def get_subscription(self, reference: str) -> Subscription:
        payload = self._server_api().get_subscription_statuses(reference)
        from bapp_connectors.providers.appstore.apple.jws import decode_signed_payload
        from bapp_connectors.providers.appstore.apple.mappers import subscription_from_server_status

        for group in payload.get("data", []):
            for last in group.get("lastTransactions", []):
                if (
                    str(last.get("originalTransactionId")) == str(reference)
                    or len(group.get("lastTransactions", [])) == 1
                ):
                    transaction = decode_signed_payload(last.get("signedTransactionInfo", ""))
                    renewal = (
                        decode_signed_payload(last.get("signedRenewalInfo", ""))
                        if last.get("signedRenewalInfo")
                        else {}
                    )
                    return subscription_from_server_status(int(last.get("status", 0)), transaction, renewal)
        raise LookupError(f"Apple: niciun abonament pentru {reference}")

    # ── FinancialCapability ──

    def get_financial_transactions(
        self,
        start_date: datetime,
        end_date: datetime,
        transaction_type: str | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[FinancialTransaction]:
        periods = fiscal_periods_between(start_date.date(), end_date.date())
        if not periods:
            return PaginatedResult(items=[], has_more=False)
        period = cursor or periods[0]
        index = periods.index(period) if period in periods else 0
        next_cursor = periods[index + 1] if index + 1 < len(periods) else None
        content = self.client.download_finance_report(period)
        rows = gunzip_tsv_rows(content) if content else []
        items = [transaction_from_finance_row(row, period) for row in rows]
        if transaction_type:
            items = [t for t in items if t.transaction_type == transaction_type]
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    # ── WebhookCapability (implementat in Task 7) ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        raise NotImplementedError("Task 7")

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        raise NotImplementedError("Task 7")
