"""
Pinterest API v5 client — raw HTTP calls only, no business logic.

Auth is a Bearer user access token applied by the shared HTTP client. Non-2xx
responses raise framework errors from the shared client; successful bodies are
returned as-is and normalized in the adapter via mappers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence  # noqa: TC003 -- runtime: get_type_hints on the AI reads
from typing import TYPE_CHECKING, Annotated

from bapp_connectors.core.ai import ai_method

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class PinterestApiClient:
    """
    Low-level Pinterest API v5 client.

    This class only handles HTTP calls. Data normalization happens in the
    adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    @ai_method(
        "read", "The connected Pinterest account: username, account type, business name, follower and pin counts."
    )
    def get_user_account(self) -> dict:
        """GET user_account — the connected account's profile."""
        return self.http.call("GET", "user_account")

    @ai_method("read", "List the account's pins, newest first. Paginate with the 'bookmark' from the previous page.")
    def list_pins(self, page_size: int = 25, bookmark: Annotated[str, "free_text"] | None = None) -> dict:
        """GET pins — returns ``{"items": [...], "bookmark": "..."}``."""
        params: dict = {"page_size": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        return self.http.call("GET", "pins", params=params)

    @ai_method("read", "Get one pin by its ID.")
    def get_pin(self, pin_id: str) -> dict:
        """GET pins/{pin_id} — a single pin."""
        return self.http.call("GET", f"pins/{pin_id}")

    @ai_method(
        "read",
        "Metrics of one pin between start_date and end_date (YYYY-MM-DD); metric_types e.g. IMPRESSION, "
        "SAVE, PIN_CLICK, OUTBOUND_CLICK, VIDEO_MRC_VIEW.",
    )
    def get_pin_analytics(
        self,
        pin_id: str,
        start_date: str,
        end_date: str,
        metric_types: Sequence[str],
    ) -> dict:
        """GET pins/{pin_id}/analytics — per-pin metrics over a date range."""
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "metric_types": ",".join(metric_types),
        }
        return self.http.call("GET", f"pins/{pin_id}/analytics", params=params)

    @ai_method("read", "Account-level metrics between start_date and end_date (YYYY-MM-DD).")
    def get_user_analytics(self, start_date: str, end_date: str) -> dict:
        """GET user_account/analytics — account-level metrics over a date range."""
        params = {"start_date": start_date, "end_date": end_date}
        return self.http.call("GET", "user_account/analytics", params=params)

    @ai_method("write", "Create a pin on a board from a Pinterest pin payload.")
    def create_pin(self, payload: dict) -> dict:
        """POST pins — create a pin; returns the created pin object with ``id``."""
        return self.http.call("POST", "pins", json=payload)
