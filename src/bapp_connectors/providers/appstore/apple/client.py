"""
Clientul HTTP Apple — doar apeluri brute.

Doua host-uri:
  - App Store Connect API  https://api.appstoreconnect.apple.com/v1/  (rapoarte, aplicatii, recenzii)
  - App Store Server API   https://api.storekit.itunes.apple.com/inApps/v1/  (abonamente; cere cheia In-App Purchase)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bapp_connectors.providers.appstore.apple.errors import raise_for_report_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

CONNECT_BASE_URL = "https://api.appstoreconnect.apple.com/v1/"
SERVER_API_BASE_URL = "https://api.storekit.itunes.apple.com/inApps/v1/"
SERVER_API_SANDBOX_BASE_URL = "https://api.storekit-sandbox.itunes.apple.com/inApps/v1/"

#: Versiunile raportului de vanzari acceptate de API (daca Apple le schimba, 400-ul cu
#: textul „version ... is not valid" ajunge in PermanentProviderError si se corecteaza aici).
SALES_REPORT_VERSION = "1_1"


class AppleApiClient:
    def __init__(self, http_client: ResilientHttpClient, vendor_number: str):
        self.http = http_client
        self.vendor_number = vendor_number

    # ── auth ──

    def test_auth(self) -> bool:
        try:
            self.http.call("GET", "apps", params={"limit": "1"})
            return True
        except Exception:
            return False

    # ── rapoarte (gzip) ──

    def _download(self, path: str, params: dict[str, str], *, what: str) -> bytes | None:
        response = self.http.call(
            "GET",
            path,
            params=params,
            headers={"Accept": "application/a-gzip"},
            direct_response=True,
        )
        if getattr(response, "status_code", 0) == 404:
            return None  # raport inca nepublicat / fara vanzari in ziua respectiva
        if not getattr(response, "ok", False):
            raise_for_report_response(response, what=what)
        return response.content

    def download_sales_report(
        self,
        report_date: str,
        report_type: str = "SALES",
        frequency: str = "DAILY",
        sub_type: str = "SUMMARY",
        version: str = SALES_REPORT_VERSION,
    ) -> bytes | None:
        params = {
            "filter[frequency]": frequency,
            "filter[reportDate]": report_date,
            "filter[reportSubType]": sub_type,
            "filter[reportType]": report_type,
            "filter[vendorNumber]": self.vendor_number,
            "filter[version]": version,
        }
        return self._download("salesReports", params, what=f"salesReports {report_type} {report_date}")

    def download_finance_report(
        self,
        fiscal_period: str,
        report_type: str = "FINANCE_DETAIL",
        region_code: str = "Z1",
    ) -> bytes | None:
        params = {
            "filter[regionCode]": region_code,
            "filter[reportDate]": fiscal_period,
            "filter[reportType]": report_type,
            "filter[vendorNumber]": self.vendor_number,
        }
        return self._download("financeReports", params, what=f"financeReports {report_type} {fiscal_period}")

    # ── aplicatii ──

    def list_apps(self) -> list[dict]:
        items: list[dict] = []
        path: str | None = "apps"
        params: dict[str, Any] | None = {"limit": "200", "fields[apps]": "name,bundleId,sku"}
        while path:
            page = self.http.call("GET", path, params=params)
            items.extend(page.get("data", []))
            path = (page.get("links") or {}).get("next")
            params = None  # link-ul `next` e absolut si contine deja parametrii
        return items

    # ── recenzii ──

    def list_reviews(self, app_id: str, next_url: str | None = None, limit: int = 200) -> dict:
        if next_url:
            return self.http.call("GET", next_url)
        return self.http.call(
            "GET",
            f"apps/{app_id}/customerReviews",
            params={"sort": "-createdDate", "include": "response", "limit": str(limit)},
        )

    def create_review_response(self, review_id: str, text: str) -> dict:
        body = {
            "data": {
                "type": "customerReviewResponses",
                "attributes": {"responseBody": text},
                "relationships": {"review": {"data": {"type": "customerReviews", "id": review_id}}},
            }
        }
        return self.http.call("POST", "customerReviewResponses", json=body, retry=False)


class AppleServerApiClient:
    """App Store Server API — foloseste un ResilientHttpClient cu AppleJwtAuth(bundle_id=...)."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def get_subscription_statuses(self, original_transaction_id: str) -> dict:
        return self.http.call("GET", f"subscriptions/{original_transaction_id}")
