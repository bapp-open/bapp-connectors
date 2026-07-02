"""
TikTok Business API v1.3 client — raw HTTP calls only, no business logic.

Auth is via the ``Access-Token`` header sent on every request. GET endpoints
take query parameters (complex values like ``filtering`` are JSON-encoded
strings); POST endpoints take a JSON body that includes ``advertiser_id``.

Every response is the standard envelope
``{"code": 0, "message": "OK", "request_id": ..., "data": {...}}`` and is run
through :func:`~bapp_connectors.providers.ads.tiktok.errors.check_response`.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from bapp_connectors.providers.ads.tiktok.errors import check_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class TikTokAdsClient:
    """
    Low-level TikTok Business API client.

    This class only handles HTTP calls and envelope unwrapping.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, access_token: str, advertiser_id: str):
        self.http = http_client
        self.access_token = access_token
        self.advertiser_id = advertiser_id

    # ── Internals ──

    def _headers(self) -> dict:
        return {"Access-Token": self.access_token}

    def _get(self, path: str, params: dict) -> dict:
        """GET with the advertiser_id and Access-Token header; returns envelope data."""
        query = {"advertiser_id": self.advertiser_id, **params}
        # TikTok GET endpoints expect complex parameters (filtering, dimensions,
        # metrics, ...) as JSON-encoded strings.
        encoded = {key: json.dumps(value) if isinstance(value, list | dict) else value for key, value in query.items()}
        response = self.http.call("GET", path, headers=self._headers(), params=encoded)
        return check_response(response)

    def _post(self, path: str, payload: dict) -> dict:
        """POST a JSON body including advertiser_id; returns envelope data."""
        body = {"advertiser_id": self.advertiser_id, **payload}
        response = self.http.call("POST", path, headers=self._headers(), json=body)
        return check_response(response)

    def _post_upload(self, path: str, payload: dict | None, files: dict | None, data: dict | None) -> dict:
        """POST an upload endpoint — JSON for UPLOAD_BY_URL, multipart for UPLOAD_BY_FILE.

        advertiser_id is merged into the JSON body (URL uploads) or into the
        multipart form fields (file uploads), matching other POST endpoints.
        """
        if files is not None:
            form = {"advertiser_id": self.advertiser_id, **(data or {})}
            response = self.http.call("POST", path, headers=self._headers(), files=files, data=form)
        else:
            body = {"advertiser_id": self.advertiser_id, **(payload or {})}
            response = self.http.call("POST", path, headers=self._headers(), json=body)
        return check_response(response)

    # ── Campaigns ──

    def get_campaigns(self, page: int = 1, page_size: int = 20, campaign_ids: list[str] | None = None) -> dict:
        """campaign/get/ — list campaigns, optionally filtered by IDs."""
        params: dict = {"page": page, "page_size": page_size}
        if campaign_ids:
            params["filtering"] = {"campaign_ids": campaign_ids}
        return self._get("campaign/get/", params)

    def create_campaign(self, payload: dict) -> dict:
        """campaign/create/ — returns {"campaign_id": ...}."""
        return self._post("campaign/create/", payload)

    def update_campaign(self, payload: dict) -> dict:
        """campaign/update/ — payload must include campaign_id."""
        return self._post("campaign/update/", payload)

    def update_campaign_status(self, campaign_ids: list[str], operation_status: str) -> dict:
        """campaign/status/update/ — operation_status is ENABLE, DISABLE, or DELETE."""
        return self._post(
            "campaign/status/update/",
            {"campaign_ids": campaign_ids, "operation_status": operation_status},
        )

    # ── Ad groups ──

    def get_adgroups(
        self,
        page: int = 1,
        page_size: int = 20,
        campaign_id: str | None = None,
        adgroup_ids: list[str] | None = None,
    ) -> dict:
        """adgroup/get/ — list ad groups, optionally filtered by campaign or IDs."""
        params: dict = {"page": page, "page_size": page_size}
        filtering: dict = {}
        if campaign_id:
            filtering["campaign_ids"] = [campaign_id]
        if adgroup_ids:
            filtering["adgroup_ids"] = adgroup_ids
        if filtering:
            params["filtering"] = filtering
        return self._get("adgroup/get/", params)

    def create_adgroup(self, payload: dict) -> dict:
        """adgroup/create/ — returns {"adgroup_id": ...}."""
        return self._post("adgroup/create/", payload)

    def update_adgroup(self, payload: dict) -> dict:
        """adgroup/update/ — payload must include adgroup_id."""
        return self._post("adgroup/update/", payload)

    def update_adgroup_status(self, adgroup_ids: list[str], operation_status: str) -> dict:
        """adgroup/status/update/ — operation_status is ENABLE, DISABLE, or DELETE."""
        return self._post(
            "adgroup/status/update/",
            {"adgroup_ids": adgroup_ids, "operation_status": operation_status},
        )

    # ── Ads ──

    def get_ads(
        self,
        page: int = 1,
        page_size: int = 20,
        adgroup_id: str | None = None,
        ad_ids: list[str] | None = None,
    ) -> dict:
        """ad/get/ — list ads, optionally filtered by ad group or IDs."""
        params: dict = {"page": page, "page_size": page_size}
        filtering: dict = {}
        if adgroup_id:
            filtering["adgroup_ids"] = [adgroup_id]
        if ad_ids:
            filtering["ad_ids"] = ad_ids
        if filtering:
            params["filtering"] = filtering
        return self._get("ad/get/", params)

    def create_ad(self, payload: dict) -> dict:
        """ad/create/ — returns {"ad_ids": [...], "creatives": [...]}."""
        return self._post("ad/create/", payload)

    def update_ad(self, payload: dict) -> dict:
        """ad/update/ — payload carries creatives with ad_id."""
        return self._post("ad/update/", payload)

    def update_ad_status(self, ad_ids: list[str], operation_status: str) -> dict:
        """ad/status/update/ — operation_status is ENABLE, DISABLE, or DELETE."""
        return self._post(
            "ad/status/update/",
            {"ad_ids": ad_ids, "operation_status": operation_status},
        )

    # ── Media uploads ──

    def upload_image(self, payload: dict | None = None, files: dict | None = None, data: dict | None = None) -> dict:
        """file/image/ad/upload/ — JSON body (UPLOAD_BY_URL) or multipart (UPLOAD_BY_FILE)."""
        return self._post_upload("file/image/ad/upload/", payload, files, data)

    def upload_video(self, payload: dict | None = None, files: dict | None = None, data: dict | None = None) -> dict:
        """file/video/ad/upload/ — JSON body (UPLOAD_BY_URL) or multipart (UPLOAD_BY_FILE)."""
        return self._post_upload("file/video/ad/upload/", payload, files, data)

    # ── Reporting ──

    def get_report(self, params: dict) -> dict:
        """report/integrated/get/ — synchronous integrated report."""
        return self._get("report/integrated/get/", params)
