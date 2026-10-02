"""
Clientul Google Play — doar HTTP.

  - Cloud Storage JSON API (rapoartele din bucket-ul pubsite_prod_rev_*): base_url
  - Android Publisher v3 (recenzii live, cumparaturi anulate, abonamente): URL absolut
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from bapp_connectors.providers.appstore.google_play.errors import raise_for_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

STORAGE_BASE_URL = "https://storage.googleapis.com/storage/v1/"
PUBLISHER_BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/"


class GooglePlayApiClient:
    def __init__(self, http_client: ResilientHttpClient, bucket: str):
        self.http = http_client
        self.bucket = bucket

    def test_auth(self) -> bool:
        try:
            self.http.call("GET", f"b/{self.bucket}/o", params={"maxResults": "1"})
            return True
        except Exception:
            return False

    # ── Cloud Storage ──

    def list_objects(self, prefix: str) -> list[dict]:
        items: list[dict] = []
        token: str | None = None
        while True:
            params = {"prefix": prefix, "fields": "items(name,size,updated),nextPageToken"}
            if token:
                params["pageToken"] = token
            page = self.http.call("GET", f"b/{self.bucket}/o", params=params)
            items.extend(page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                return items

    def download_object(self, name: str) -> bytes:
        response = self.http.call("GET", f"b/{self.bucket}/o/{quote(name, safe='')}", params={"alt": "media"}, direct_response=True)
        if not getattr(response, "ok", False):
            raise_for_response(response, what=f"download {name}")
        return response.content

    # ── Android Publisher ──

    def list_reviews(self, package_name: str, token: str | None = None, max_results: int = 100) -> dict:
        params = {"maxResults": str(max_results)}
        if token:
            params["token"] = token
        return self.http.call("GET", f"{PUBLISHER_BASE_URL}{package_name}/reviews", params=params)

    def reply_review(self, package_name: str, review_id: str, text: str) -> dict:
        return self.http.call("POST", f"{PUBLISHER_BASE_URL}{package_name}/reviews/{review_id}:reply", json={"replyText": text}, retry=False)

    def list_voided_purchases(self, package_name: str, start_ms: int, end_ms: int, token: str | None = None) -> dict:
        params = {"startTime": str(start_ms), "endTime": str(end_ms), "type": "1", "maxResults": "1000"}
        if token:
            params["token"] = token
        return self.http.call("GET", f"{PUBLISHER_BASE_URL}{package_name}/purchases/voidedpurchases", params=params)

    def get_subscription_v2(self, package_name: str, purchase_token: str) -> dict:
        return self.http.call("GET", f"{PUBLISHER_BASE_URL}{package_name}/purchases/subscriptionsv2/tokens/{purchase_token}")
