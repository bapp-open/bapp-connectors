"""Adapterul Steam — AppStorePort + FinancialCapability (fara recenzii cu raspuns, abonamente sau webhooks)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from bapp_connectors.core.capabilities import FinancialCapability
from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    ConnectionTestResult,
    FinancialTransaction,
    PaginatedResult,
)
from bapp_connectors.core.errors import AuthenticationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.reports import daily_page
from bapp_connectors.providers.appstore.steam.client import SteamApiClient
from bapp_connectors.providers.appstore.steam.errors import steam_forbidden_hint
from bapp_connectors.providers.appstore.steam.manifest import manifest
from bapp_connectors.providers.appstore.steam.mappers import (
    app_from_details,
    refunds_from_detailed,
    review_from_steam,
    sales_from_detailed,
    transactions_from_detailed,
)


def _parse_steam_date(text: str) -> date:
    """Accepta YYYY-MM-DD, YYYY/MM/DD si YYYYMMDD."""
    value = str(text).strip().replace("/", "-")
    if len(value) == 8 and value.isdigit():
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return date.fromisoformat(value)


class SteamAdapter(AppStorePort, FinancialCapability):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}
        self.app_ids = [a.strip() for a in (credentials.get("app_ids") or "").split(",") if a.strip()]
        if http_client is None:
            http_client = ResilientHttpClient(base_url=self.manifest.base_url, provider_name="steam")
        self.http = http_client
        self.client = SteamApiClient(http_client=http_client, api_key=credentials.get("financial_api_key", ""))

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            self.client.get_changed_dates(0)
            return ConnectionTestResult(success=True, message="Connection successful")
        except AuthenticationError as exc:
            return ConnectionTestResult(success=False, message=f"{steam_forbidden_hint()} ({exc})")
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))

    def changed_dates(self, highwatermark: int = 0) -> tuple[list[date], int]:
        """Zilele revizuite de Valve de la ultimul highwatermark; apelantul le re-aduce cu get_sales."""
        response = self.client.get_changed_dates(highwatermark)
        days = [_parse_steam_date(d) for d in response.get("dates", []) or []]
        return days, int(response.get("result_highwatermark", highwatermark) or highwatermark)

    def list_apps(self) -> list[AppStoreApp]:
        apps = []
        for app_id in self.app_ids:
            try:
                details = self.client.get_app_details(app_id)
            except Exception:  # endpoint public, fara garantii
                details = None
            apps.append(app_from_details(app_id, details))
        return apps

    def get_sales(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreSale]:
        day, next_cursor = daily_page(start, end, cursor)
        items = sales_from_detailed(self.client.get_detailed_sales(day), day)
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def list_refunds(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreRefund]:
        day, next_cursor = daily_page(start, end, cursor)
        items = refunds_from_detailed(self.client.get_detailed_sales(day), day)
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def list_reviews(self, app_id: str, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[AppStoreReview]:
        page = self.client.get_reviews(app_id, cursor=cursor or "*")
        items = [review_from_steam(r, app_id) for r in page.get("reviews", []) or []]
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            items = [r for r in items if r.created_at is None or r.created_at >= since]
        next_cursor = page.get("cursor")
        has_more = bool(items) and bool(next_cursor) and next_cursor != cursor
        return PaginatedResult(items=items, cursor=next_cursor if has_more else None, has_more=has_more)

    def get_financial_transactions(self, start_date: datetime, end_date: datetime, transaction_type: str | None = None, cursor: str | None = None) -> PaginatedResult[FinancialTransaction]:
        day, next_cursor = daily_page(start_date.date(), end_date.date(), cursor)
        items = transactions_from_detailed(self.client.get_detailed_sales(day), day)
        if transaction_type:
            items = [t for t in items if t.transaction_type == transaction_type]
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)
