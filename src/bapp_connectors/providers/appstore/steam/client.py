"""Clientul Steamworks — cheia merge in query string; store.steampowered.com e public."""

from __future__ import annotations

from datetime import date  # noqa: TC003 -- runtime: get_type_hints on the AI reads
from typing import TYPE_CHECKING, Annotated

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.providers.appstore.steam.errors import check_steam_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

STORE_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_REVIEWS_URL = "https://store.steampowered.com/appreviews/"
STORE_PLAYERS_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"


class SteamApiClient:
    def __init__(self, http_client: ResilientHttpClient, api_key: str):
        self.http = http_client
        self.api_key = api_key

    @ai_method(
        "read",
        "Dates whose Steam sales data changed since highwatermark (0 = all); returns the dates and the "
        "new highwatermark. Nothing is acknowledged.",
    )
    def get_changed_dates(self, highwatermark: int = 0) -> dict:
        payload = self.http.call("GET", "IPartnerFinancialsService/GetChangedDatesForPartner/v001/", params={"key": self.api_key, "highwatermark": str(highwatermark)})
        return check_steam_response(payload, what="GetChangedDatesForPartner")

    @ai_method("read", "Detailed Steam sales of one day (YYYY-MM-DD): rows per app/package/country, with app and package names.")
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
        else:
            raise PermanentProviderError(f"Steam GetDetailedSales {day}: peste 1000 de pagini, date incomplete")
        return merged

    @ai_method("read", "Public store details of a Steam app (name, type, description, price, platforms).")
    def get_app_details(self, app_id: str) -> dict:
        return self.http.call("GET", STORE_APPDETAILS_URL, params={"appids": str(app_id), "filters": "basic"})

    @ai_method(
        "read",
        "Recent public reviews of a Steam app, all languages, with the review summary. "
        "Pass back the returned cursor to get the next page ('*' = first page).",
    )
    def get_reviews(self, app_id: str, cursor: Annotated[str, "free_text"] = "*", num_per_page: int = 100) -> dict:
        return self.http.call("GET", f"{STORE_REVIEWS_URL}{app_id}", params={"json": "1", "cursor": cursor, "num_per_page": str(num_per_page), "filter": "recent", "language": "all", "purchase_type": "all"})

    @ai_method("read", "Wishlist adds, deletes, purchases and gifts of a Steam app on one day (YYYY-MM-DD).")
    def get_wishlist_reporting(self, app_id: str, day: date) -> dict:
        payload = self.http.call("GET", "IPartnerFinancialsService/GetAppWishlistReporting/v001/", params={"key": self.api_key, "appid": str(app_id), "date": day.isoformat()})
        return check_steam_response(payload, what=f"GetAppWishlistReporting {day}")

    @ai_method("read", "Number of players currently in a Steam app.")
    def get_current_players(self, app_id: str) -> int:
        """Endpoint public: fara cheie."""
        payload = self.http.call("GET", STORE_PLAYERS_URL, params={"appid": str(app_id)})
        return int(((payload or {}).get("response") or {}).get("player_count", 0) or 0)
