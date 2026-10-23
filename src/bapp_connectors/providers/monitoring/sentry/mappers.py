"""Conversions between raw Sentry REST / integration-webhook payloads and framework DTOs.

Every mapper reads the raw dict defensively: Sentry nulls or omits many keys depending on
the endpoint (list vs detail), the issue type and the caller's permissions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bapp_connectors.core.dto import WebhookEvent, WebhookEventType
from bapp_connectors.core.dto.monitoring import ErrorIssue, MonitoredProject, MonitoredProjectStats

_ISSUE_ACTIONS = {
    "created": WebhookEventType.ERROR_ISSUE_CREATED,
    "resolved": WebhookEventType.ERROR_ISSUE_RESOLVED,
    "unresolved": WebhookEventType.ERROR_ISSUE_UNRESOLVED,
    "ignored": WebhookEventType.ERROR_ISSUE_IGNORED,
    "assigned": WebhookEventType.ERROR_ISSUE_ASSIGNED,
}
_STATS_FIELD = "sum(quantity)"


def _dt(value: Any) -> datetime | None:
    """Parse a Sentry ISO timestamp (`...Z`, optional microseconds) into an aware datetime; None when absent or invalid."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _obj(raw: Any) -> dict:
    return raw if isinstance(raw, dict) else {}


def _int(value: Any) -> int:
    """Sentry sends some counters (e.g. an issue's `count`) as strings."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def map_project(raw: dict, host: str, org: str) -> MonitoredProject:
    """`GET /organizations/:org/projects/` item or `GET /projects/:org/:slug/` to a MonitoredProject keyed by slug."""
    slug = raw.get("slug") or ""
    return MonitoredProject(
        ref=slug,
        name=raw.get("name") or slug,
        slug=slug,
        platform=raw.get("platform") or "",
        web_url=f"https://{host}/organizations/{org}/projects/{slug}/",
        # The list endpoint omits `status`; only the detail payload carries it.
        is_active=(raw.get("status") or "active") == "active",
        extra={"id": str(raw.get("id") or "")},
    )


def map_issue(raw: dict) -> ErrorIssue:
    """`GET /projects/:org/:slug/issues/` item or `GET /issues/:id/` to an ErrorIssue of its project's slug."""
    assignee = _obj(raw.get("assignedTo"))
    return ErrorIssue(
        ref=_obj(raw.get("project")).get("slug") or "",
        id=str(raw.get("id") or ""),
        short_id=raw.get("shortId") or "",
        title=raw.get("title") or "",
        culprit=raw.get("culprit") or "",
        level=raw.get("level") or "error",
        status=raw.get("status") or "unresolved",
        count=_int(raw.get("count")),
        user_count=_int(raw.get("userCount")),
        first_seen=_dt(raw.get("firstSeen")),
        last_seen=_dt(raw.get("lastSeen")),
        is_unhandled=bool(raw.get("isUnhandled", False)),
        # A team assignee has a name but no email.
        assigned_to=assignee.get("email") or assignee.get("name") or "",
        permalink=raw.get("permalink") or "",
        extra={
            "type": raw.get("type"),
            "metadata": _obj(raw.get("metadata")),
            "logger": raw.get("logger"),
            "platform": raw.get("platform"),
        },
    )


def map_stats(raw: dict, ref: str, period: str) -> MonitoredProjectStats:
    """`GET /organizations/:org/stats_v2/` grouped by outcome to MonitoredProjectStats.

    `accepted` events were stored; every other outcome (filtered, rate_limited, invalid,
    client_discard, ...) was received but dropped.
    """
    accepted = total = 0
    for group in _obj(raw).get("groups") or []:
        group = _obj(group)
        quantity = _int(_obj(group.get("totals")).get(_STATS_FIELD))
        total += quantity
        if _obj(group.get("by")).get("outcome") == "accepted":
            accepted += quantity
    return MonitoredProjectStats(
        ref=ref,
        period=period,
        events=accepted,
        errors_received=total,
        errors_rejected=total - accepted,
    )


def _header(headers: dict, name: str) -> str:
    lowered = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == lowered:
            return str(value or "")
    return ""


def webhook_event_from_sentry(headers: dict, payload: dict) -> WebhookEvent:
    """Map a Sentry integration-webhook delivery (headers read case-insensitively) to a normalized WebhookEvent."""
    payload = payload or {}
    resource = _header(headers, "Sentry-Hook-Resource")
    action = payload.get("action") or ""
    request_id = _header(headers, "Request-ID")
    event_type = WebhookEventType.UNKNOWN
    if resource == "issue":
        event_type = _ISSUE_ACTIONS.get(action, WebhookEventType.UNKNOWN)
    issue_id = _obj(_obj(payload.get("data")).get("issue")).get("id", "")

    return WebhookEvent(
        event_id=request_id,
        event_type=event_type,
        provider="sentry",
        provider_event_type=f"{resource}:{action}",
        payload=payload,
        idempotency_key=request_id or f"{action}:{issue_id}",
        received_at=datetime.now(UTC),
    )
