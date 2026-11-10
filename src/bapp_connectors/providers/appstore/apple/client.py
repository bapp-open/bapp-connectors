"""
Clientul HTTP Apple — doar apeluri brute.

Doua host-uri:
  - App Store Connect API  https://api.appstoreconnect.apple.com/v1/  (rapoarte, aplicatii, recenzii)
  - App Store Server API   https://api.storekit.itunes.apple.com/inApps/v1/  (abonamente; cere cheia In-App Purchase)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import parse_qs, urlsplit

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.appstore.apple.errors import raise_for_report_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

CONNECT_BASE_URL = "https://api.appstoreconnect.apple.com/v1/"
SERVER_API_BASE_URL = "https://api.storekit.itunes.apple.com/inApps/v1/"
SERVER_API_SANDBOX_BASE_URL = "https://api.storekit-sandbox.itunes.apple.com/inApps/v1/"

#: Versiunile raportului de vanzari acceptate de API (daca Apple le schimba, 400-ul cu
#: textul „version ... is not valid" ajunge in PermanentProviderError si se corecteaza aici).
SALES_REPORT_VERSION = "1_1"


AI_VERSION_FIELDS = "platform,versionString,appStoreState,appVersionState,releaseType,earliestReleaseDate,createdDate"


CONNECT_HOST = "api.appstoreconnect.apple.com"
_APP_ID = re.compile(r"[0-9]+")


def _app_id(value: str) -> str:
    """An App Store Connect app id: digits only (it goes into the URL path)."""
    if not isinstance(value, str) or not _APP_ID.fullmatch(value):
        raise ValidationError("app_id must be a numeric App Store Connect app id.")
    return value


def connect_next_link(page: dict) -> str | None:
    """``links.next`` of a page when it is an https URL on the App Store Connect host, else None.

    The client's JWT goes with every call, so a link to any other host is never followed."""
    link = (page.get("links") or {}).get("next") if isinstance(page, dict) else None
    if not isinstance(link, str) or not link:
        return None
    parts = urlsplit(link)
    if parts.scheme != "https" or parts.hostname != CONNECT_HOST or parts.port is not None or parts.username:
        return None
    return link


def next_cursor(page: dict) -> str | None:
    """The ``cursor`` query parameter of a page's ``links.next`` (None on the last page)."""
    link = (page.get("links") or {}).get("next") if isinstance(page, dict) else None
    if not link:
        return None
    return (parse_qs(urlsplit(link).query).get("cursor") or [None])[0]


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
        # 404 = raport inca nepublicat / fara vanzari in ziua respectiva.
        # 410 = retentie depasita; Apple: "Report is no longer available. Daily reports are available for
        # 365 days, weekly reports for 52 weeks, monthly reports for 12 months, and yearly reports indefinitely."
        if getattr(response, "status_code", 0) in (404, 410):
            return None
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

    @ai_method("read", "Every app of the App Store Connect account: name, bundle ID, SKU.")
    def list_apps(self) -> list[dict]:
        items: list[dict] = []
        path: str | None = "apps"
        params: dict[str, Any] | None = {"limit": "200", "fields[apps]": "name,bundleId,sku"}
        while path:
            page = self.http.call("GET", path, params=params)
            items.extend(page.get("data", []))
            path = connect_next_link(page)
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

    @ai_method(
        "read",
        "Customer reviews of an app, newest first, with the developer response when there is one. "
        "Pass back next_cursor to get the next page.",
    )
    def list_app_reviews(
        self, app_id: str, cursor: Annotated[str, "free_text"] | None = None, limit: int = 100
    ) -> dict:
        params = {"sort": "-createdDate", "include": "response", "limit": str(max(1, min(int(limit), 200)))}
        if cursor:
            params["cursor"] = cursor
        page = self.http.call("GET", f"apps/{_app_id(app_id)}/customerReviews", params=params)
        return {"data": page.get("data", []), "included": page.get("included", []), "next_cursor": next_cursor(page)}

    @ai_method(
        "read",
        "App Store versions of an app (platform, version, state, release type, dates), newest first. "
        "Pass back next_cursor to get the next page.",
    )
    def list_app_versions(
        self, app_id: str, cursor: Annotated[str, "free_text"] | None = None, limit: int = 50
    ) -> dict:
        params = {"fields[appStoreVersions]": AI_VERSION_FIELDS, "limit": str(max(1, min(int(limit), 200)))}
        if cursor:
            params["cursor"] = cursor
        page = self.http.call("GET", f"apps/{_app_id(app_id)}/appStoreVersions", params=params)
        return {"data": page.get("data", []), "next_cursor": next_cursor(page)}

    @ai_method("write", "Reply to a customer review (one developer response per review).")
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
