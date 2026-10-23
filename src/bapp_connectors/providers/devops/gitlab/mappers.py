"""Conversions between raw GitLab REST / webhook payloads and framework DTOs.

Every mapper reads the raw dict defensively: GitLab omits or nulls many keys depending on
the endpoint, the instance version and the caller's permissions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bapp_connectors.core.dto import WebhookEvent, WebhookEventType
from bapp_connectors.core.dto.devops import (
    Commit,
    Issue,
    IssueComment,
    IssueDraft,
    MergeRequest,
    Pipeline,
    Repository,
)

_ISSUE_ACTIONS = {
    "open": WebhookEventType.ISSUE_OPENED,
    "update": WebhookEventType.ISSUE_UPDATED,
    "close": WebhookEventType.ISSUE_CLOSED,
    "reopen": WebhookEventType.ISSUE_REOPENED,
}
_MERGE_REQUEST_ACTIONS = {
    "open": WebhookEventType.MERGE_REQUEST_OPENED,
    "merge": WebhookEventType.MERGE_REQUEST_MERGED,
    "close": WebhookEventType.MERGE_REQUEST_CLOSED,
}
_PIPELINE_STATUSES = {
    "success": WebhookEventType.PIPELINE_SUCCEEDED,
    "failed": WebhookEventType.PIPELINE_FAILED,
}


def _dt(value: Any) -> datetime | None:
    """Parse a GitLab timestamp into an aware datetime; None when absent or invalid.

    REST sends ISO 8601 (`...Z` or `+hh:mm`); webhooks send `YYYY-MM-DD HH:MM:SS UTC`
    (or `... +hhmm`), whose ` UTC` suffix `fromisoformat` does not accept.
    """
    if not value or not isinstance(value, str):
        return None
    if value.endswith(" UTC"):
        value = value[: -len(" UTC")] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _obj(raw: Any) -> dict:
    return raw if isinstance(raw, dict) else {}


def map_repository(raw: dict) -> Repository:
    """`GET /projects[/:id]` item to a Repository."""
    extra = {key: raw[key] for key in ("star_count", "forks_count") if key in raw}
    return Repository(
        ref=str(raw.get("id", "")),
        name=raw.get("name") or "",
        full_path=raw.get("path_with_namespace") or "",
        description=raw.get("description") or "",
        web_url=raw.get("web_url") or "",
        default_branch=raw.get("default_branch") or "",
        visibility=raw.get("visibility") or "",
        archived=bool(raw.get("archived", False)),
        last_activity_at=_dt(raw.get("last_activity_at")),
        open_issues_count=raw.get("open_issues_count"),
        topics=list(raw.get("topics") or []),
        namespace=_obj(raw.get("namespace")).get("full_path") or "",
        extra=extra,
    )


def map_issue(raw: dict) -> Issue:
    """`GET /projects/:id/issues` item to an Issue; `number` is the per-project iid."""
    author = _obj(raw.get("author"))
    assignees = [_obj(a) for a in raw.get("assignees") or []]
    return Issue(
        ref=str(raw.get("project_id", "")),
        number=int(raw.get("iid") or 0),
        title=raw.get("title") or "",
        description=raw.get("description") or "",
        state=raw.get("state") or "opened",
        labels=list(raw.get("labels") or []),
        author=author.get("name") or "",
        assignees=[a.get("name") or "" for a in assignees],
        web_url=raw.get("web_url") or "",
        created_at=_dt(raw.get("created_at")),
        updated_at=_dt(raw.get("updated_at")),
        closed_at=_dt(raw.get("closed_at")),
        extra={
            "author_username": author.get("username") or "",
            "assignee_ids": [a["id"] for a in assignees if "id" in a],
            "milestone": raw.get("milestone"),
        },
    )


def map_merge_request(raw: dict) -> MergeRequest:
    """`GET /projects/:id/merge_requests` item to a MergeRequest; `number` is the per-project iid."""
    return MergeRequest(
        ref=str(raw.get("project_id", "")),
        number=int(raw.get("iid") or 0),
        title=raw.get("title") or "",
        state=raw.get("state") or "opened",
        source_branch=raw.get("source_branch") or "",
        target_branch=raw.get("target_branch") or "",
        author=_obj(raw.get("author")).get("name") or "",
        web_url=raw.get("web_url") or "",
        created_at=_dt(raw.get("created_at")),
        merged_at=_dt(raw.get("merged_at")),
    )


def map_commit(raw: dict, ref: str) -> Commit:
    """`GET /projects/:id/repository/commits` item to a Commit of repository `ref`."""
    return Commit(
        ref=ref,
        sha=raw.get("id") or "",
        title=raw.get("title") or "",
        author_name=raw.get("author_name") or "",
        author_email=raw.get("author_email") or "",
        authored_at=_dt(raw.get("authored_date")),
        web_url=raw.get("web_url") or "",
    )


def map_pipeline(raw: dict, ref: str) -> Pipeline:
    """`GET /projects/:id/pipelines[/:id]` item to a Pipeline of repository `ref`; `branch` is the pipeline's git ref."""
    return Pipeline(
        ref=ref,
        id=str(raw.get("id", "")),
        status=raw.get("status") or "",
        branch=raw.get("ref") or "",
        sha=raw.get("sha") or "",
        web_url=raw.get("web_url") or "",
        created_at=_dt(raw.get("created_at")),
        finished_at=_dt(raw.get("finished_at")),
    )


def map_issue_comment(raw: dict) -> IssueComment:
    """`GET|POST /projects/:id/issues/:iid/notes` item to an IssueComment."""
    return IssueComment(
        id=str(raw.get("id", "")),
        body=raw.get("body") or "",
        author=_obj(raw.get("author")).get("name") or "",
        created_at=_dt(raw.get("created_at")),
    )


def issue_draft_to_payload(draft: IssueDraft) -> dict:
    """IssueDraft to the create/update issue body: comma-joined labels, integer assignee ids."""
    return {
        "title": draft.title,
        "description": draft.description,
        "labels": ",".join(draft.labels),
        "assignee_ids": [int(a) for a in draft.assignee_ids],
    }


def _header(headers: dict, name: str) -> str:
    lowered = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == lowered:
            return str(value or "")
    return ""


def _event_type(gitlab_event: str, attributes: dict) -> WebhookEventType:
    if gitlab_event == "Push Hook":
        return WebhookEventType.REPOSITORY_PUSH
    if gitlab_event == "Issue Hook":
        return _ISSUE_ACTIONS.get(attributes.get("action") or "", WebhookEventType.UNKNOWN)
    if gitlab_event == "Note Hook":
        if attributes.get("noteable_type") == "Issue":
            return WebhookEventType.ISSUE_COMMENTED
        return WebhookEventType.UNKNOWN
    if gitlab_event == "Merge Request Hook":
        return _MERGE_REQUEST_ACTIONS.get(attributes.get("action") or "", WebhookEventType.UNKNOWN)
    if gitlab_event == "Pipeline Hook":
        return _PIPELINE_STATUSES.get(attributes.get("status") or "", WebhookEventType.UNKNOWN)
    return WebhookEventType.UNKNOWN


def webhook_event_from_gitlab(headers: dict, payload: dict) -> WebhookEvent:
    """Map a GitLab webhook delivery (headers read case-insensitively) to a normalized WebhookEvent."""
    payload = payload or {}
    gitlab_event = _header(headers, "X-Gitlab-Event")
    attributes = _obj(payload.get("object_attributes"))
    qualifier = attributes.get("action") or attributes.get("status") or ""
    event_type = _event_type(gitlab_event, attributes)

    if gitlab_event == "Push Hook":
        project_id = _obj(payload.get("project")).get("id", payload.get("project_id", ""))
        idempotency_key = f"push:{project_id}:{payload.get('checkout_sha') or ''}"
    else:
        stamp = attributes.get("updated_at") or attributes.get("finished_at") or ""
        idempotency_key = f"{payload.get('object_kind', '')}:{attributes.get('id', '')}:{stamp}"

    return WebhookEvent(
        event_id=_header(headers, "X-Gitlab-Event-UUID"),
        event_type=event_type,
        provider="gitlab",
        provider_event_type=f"{gitlab_event}:{qualifier}",
        payload=payload,
        idempotency_key=idempotency_key,
        received_at=datetime.now(UTC),
    )
