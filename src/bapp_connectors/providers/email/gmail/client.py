"""
Gmail API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with BearerAuth for OAuth2 access token.
All data normalization happens in the adapter via mappers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class GmailApiClient:
    """
    Low-level Gmail API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    # ── Profile / Connection Test ──

    def get_profile(self) -> dict:
        """
        Get the authenticated user's profile.

        Returns:
            Dict with ``emailAddress``, ``messagesTotal``, ``threadsTotal``,
            ``historyId``.
        """
        return self.http.get("profile")

    # ── Sending ──

    def send_message(self, raw_b64: str) -> dict:
        """
        Send an email message.

        Args:
            raw_b64: Base64url-encoded RFC 2822 MIME message.

        Returns:
            Dict with ``id``, ``threadId``, ``labelIds``.
        """
        return self.http.post("messages/send", json={"raw": raw_b64})

    # ── Inbox ──

    def list_messages(
        self,
        query: str = "",
        label_ids: list[str] | None = None,
        max_results: int = 50,
    ) -> dict:
        """
        List message IDs matching a query.

        Args:
            query: Gmail search query (e.g. ``"after:2024/01/01"``).
            label_ids: Filter by label IDs (e.g. ``["INBOX"]``).
            max_results: Maximum number of results to return.

        Returns:
            Dict with ``messages`` (list of ``{id, threadId}``),
            ``resultSizeEstimate``, and optionally ``nextPageToken``.
        """
        params: dict = {"maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        return self.http.get("messages", params=params)

    def get_message(self, message_id: str, fmt: str = "full") -> dict:
        """
        Get a single message.

        Args:
            message_id: Gmail message ID.
            fmt: Response format — ``"full"``, ``"metadata"``, ``"minimal"``,
                or ``"raw"``.

        Returns:
            Full message resource dict.
        """
        params: dict = {"format": fmt}
        if fmt == "metadata":
            params["metadataHeaders"] = [
                "From",
                "To",
                "Subject",
                "Date",
            ]
        return self.http.get(f"messages/{message_id}", params=params)

    def get_attachment(self, message_id: str, attachment_id: str) -> dict:
        """
        Download attachment data.

        Args:
            message_id: Gmail message ID.
            attachment_id: Attachment ID from the message payload.

        Returns:
            Dict with ``data`` (base64url-encoded) and ``size``.
        """
        return self.http.get(
            f"messages/{message_id}/attachments/{attachment_id}",
        )
