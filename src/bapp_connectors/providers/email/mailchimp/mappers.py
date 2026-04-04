"""
Mandrill mappers — convert between framework DTOs and Mandrill API payloads.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import DeliveryReport, DeliveryStatus

if TYPE_CHECKING:
    from bapp_connectors.core.dto import OutboundMessage

logger = logging.getLogger(__name__)

# Mandrill status → framework DeliveryStatus
_STATUS_MAP: dict[str, DeliveryStatus] = {
    "sent": DeliveryStatus.SENT,
    "queued": DeliveryStatus.QUEUED,
    "scheduled": DeliveryStatus.QUEUED,
    "rejected": DeliveryStatus.REJECTED,
    "invalid": DeliveryStatus.FAILED,
}


def outbound_to_mandrill(
    message: OutboundMessage,
    default_from_email: str,
    default_from_name: str = "",
) -> dict:
    """
    Convert an OutboundMessage DTO to a Mandrill ``message`` dict.

    Supports:
    - ``message.to`` as the primary recipient
    - ``message.extra["cc"]`` and ``message.extra["bcc"]`` for additional recipients
    - ``message.extra["from_email"]`` / ``message.extra["from_name"]`` to override defaults
    - ``message.subject``, ``message.body`` (text), ``message.html_body`` (html)
    - ``message.attachments`` list of dicts with ``filename``, ``content`` (bytes),
      and ``content_type`` keys
    - ``message.template_vars`` passed as Mandrill ``global_merge_vars``
    """
    extra = message.extra or {}

    from_email = extra.get("from_email", "") or default_from_email
    from_name = extra.get("from_name", "") or default_from_name

    # ── Recipients ──
    recipients: list[dict] = [{"email": message.to, "type": "to"}]

    for cc_addr in extra.get("cc", []):
        recipients.append({"email": cc_addr, "type": "cc"})

    for bcc_addr in extra.get("bcc", []):
        recipients.append({"email": bcc_addr, "type": "bcc"})

    # ── Base message ──
    mandrill_msg: dict = {
        "from_email": from_email,
        "to": recipients,
        "subject": message.subject,
    }

    if from_name:
        mandrill_msg["from_name"] = from_name

    # ── Body ──
    if message.body:
        mandrill_msg["text"] = message.body
    if message.html_body:
        mandrill_msg["html"] = message.html_body

    # ── Attachments ──
    if message.attachments:
        mandrill_attachments: list[dict] = []
        for att in message.attachments:
            content = att.get("content", b"")
            if isinstance(content, bytes):
                encoded = base64.b64encode(content).decode("ascii")
            else:
                # Already a string — assume base64-encoded
                encoded = str(content)

            mandrill_attachments.append(
                {
                    "type": att.get("content_type", "application/octet-stream"),
                    "name": att.get("filename", "attachment"),
                    "content": encoded,
                }
            )
        mandrill_msg["attachments"] = mandrill_attachments

    # ── Template merge vars ──
    if message.template_vars:
        mandrill_msg["global_merge_vars"] = [{"name": k, "content": v} for k, v in message.template_vars.items()]

    # ── Reply-to header ──
    reply_to = extra.get("reply_to", "")
    if reply_to:
        mandrill_msg["headers"] = {"Reply-To": reply_to}

    # ── Tags / metadata ──
    tags = extra.get("tags")
    if tags:
        mandrill_msg["tags"] = tags

    metadata = extra.get("metadata")
    if metadata:
        mandrill_msg["metadata"] = metadata

    return mandrill_msg


def mandrill_result_to_report(result: list[dict], message_id: str) -> DeliveryReport:
    """
    Convert a Mandrill send result list to a single DeliveryReport.

    Mandrill returns one result dict per recipient. We take the first
    (primary ``to`` recipient) as the canonical status. If the list is
    empty we report FAILED.

    Each Mandrill result dict looks like::

        {
            "email": "recipient@example.com",
            "status": "sent",       # sent | queued | scheduled | rejected | invalid
            "reject_reason": "...", # present when status == "rejected"
            "_id": "abc123..."      # Mandrill internal message ID
        }
    """
    if not result:
        return DeliveryReport(
            message_id=message_id,
            status=DeliveryStatus.FAILED,
            error="Empty response from Mandrill",
        )

    first = result[0]
    raw_status = first.get("status", "")
    status = _STATUS_MAP.get(raw_status, DeliveryStatus.FAILED)

    error = ""
    if status in (DeliveryStatus.REJECTED, DeliveryStatus.FAILED):
        error = first.get("reject_reason", "") or f"Mandrill status: {raw_status}"

    provider_id = first.get("_id", "")

    return DeliveryReport(
        message_id=message_id,
        status=status,
        error=error,
        extra={"mandrill_id": provider_id, "results": result} if provider_id else {},
    )
