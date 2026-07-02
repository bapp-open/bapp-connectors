"""
Meta Marketing API client — raw HTTP calls only, no business logic.

All paths are relative to https://graph.facebook.com/v19.0/. Account-scoped
edges live under act_{ad_account_id}/. Auth (Bearer token) is applied by the
underlying ResilientHttpClient.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from bapp_connectors.providers.ads.facebook.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class MetaAdsClient:
    """
    Low-level Meta Marketing API client.

    This class only handles HTTP calls and response parsing. Data
    normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, ad_account_id: str):
        self.http = http_client
        self.ad_account_id = ad_account_id

    def account_path(self, edge: str) -> str:
        """Build an account-scoped edge path, e.g. ``act_123/campaigns``."""
        return f"act_{self.ad_account_id}/{edge}"

    def _parse(self, response: Any) -> Any:
        """Raise framework errors for Graph API error payloads (which can arrive with HTTP 200)."""
        if isinstance(response, dict):
            check_payload(response)
        return response

    # ── Reads ──

    def list_edge(
        self,
        path: str,
        fields: str,
        limit: int | None = None,
        after: str | None = None,
        filtering: list[dict] | None = None,
    ) -> dict:
        """GET a paginated edge (campaigns, adsets, ads, ...)."""
        params: dict = {"fields": fields}
        if limit is not None:
            params["limit"] = limit
        if after:
            params["after"] = after
        if filtering:
            params["filtering"] = json.dumps(filtering)
        return self._parse(self.http.call("GET", path, params=params))

    def get_object(self, object_id: str, fields: str) -> dict:
        """GET a single Graph object by ID."""
        return self._parse(self.http.call("GET", object_id, params={"fields": fields}))

    def get_insights(self, object_id: str, params: dict) -> dict:
        """GET the insights edge of an object."""
        return self._parse(self.http.call("GET", f"{object_id}/insights", params=params))

    # ── Writes ──

    def create(self, path: str, payload: dict) -> dict:
        """POST a new object to an edge. Returns the Graph response (usually {"id": ...})."""
        return self._parse(self.http.call("POST", path, json=payload))

    def update(self, object_id: str, payload: dict) -> dict:
        """POST field updates to an existing object."""
        return self._parse(self.http.call("POST", object_id, json=payload))
