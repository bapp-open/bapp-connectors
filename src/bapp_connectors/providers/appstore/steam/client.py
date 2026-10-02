"""Clientul Steamworks — cheia merge in query string; store.steampowered.com e public."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.providers.appstore.steam.errors import check_steam_response

if TYPE_CHECKING:
    from datetime import date

    from bapp_connectors.core.http import ResilientHttpClient

STORE_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_REVIEWS_URL = "https://store.steampowered.com/appreviews/"


class SteamApiClient:
    def __init__(self, http_client: ResilientHttpClient, api_key: str):
        self.http = http_client
        self.api_key = api_key

    def get_changed_dates(self, highwatermark: int = 0) -> dict:
        payload = self.http.call("GET", "IPartnerFinancialsService/GetChangedDatesForPartner/v001/", params={"key": self.api_key, "highwatermark": str(highwatermark)})
        return check_steam_response(payload, what="GetChangedDatesForPartner")

    def get_detailed_sales(self, day: date) -> dict:
        """Aduna toate paginile zilei (highwatermark_id) intr-un singur payload."""
        merged: dict = {"results": [], "app_info": [], "package_info": [], "bundle_info": [], "country_info": []}
        watermark = 0
        for _ in range(1000):
            page = check_steam_response(
                self.http.call("GET", "IPartnerFinancialsService/GetDetailedSales/v001/", params={"key": self.api_key, "date": day.isoformat(), "highwatermark_id": str(watermark)}),
                what=f"GetDetailedSales {day}",
            )
            for key in ("results", "app_info", "package_info", "bundle_info", "country_info"):
                merged[key].extend(page.get(key, []) or [])
            max_id = int(page.get("max_id", 0) or 0)
            if max_id <= watermark or not page.get("results"):
                break
            watermark = max_id
        return merged

    def get_app_details(self, app_id: str) -> dict:
        return self.http.call("GET", STORE_APPDETAILS_URL, params={"appids": str(app_id), "filters": "basic"})

    def get_reviews(self, app_id: str, cursor: str = "*", num_per_page: int = 100) -> dict:
        return self.http.call("GET", f"{STORE_REVIEWS_URL}{app_id}", params={"json": "1", "cursor": cursor, "num_per_page": str(num_per_page), "filter": "recent", "language": "all", "purchase_type": "all"})
