"""GitLab adapter — DevOpsPort, issue writes and webhooks over REST v4."""

from __future__ import annotations

import hmac
import json
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import IssueManagementCapability, WebhookCapability
from bapp_connectors.core.dto import (
    Commit,
    ConnectionTestResult,
    Issue,
    IssueComment,
    IssueDraft,
    MergeRequest,
    PaginatedResult,
    Pipeline,
    Repository,
    WebhookEvent,
)
from bapp_connectors.core.errors import ConnectorError, ValidationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.rate_limit import RateLimiter
from bapp_connectors.core.http.retry import RetryPolicy
from bapp_connectors.core.ports import DevOpsPort
from bapp_connectors.providers.devops.gitlab.client import GitLabClient
from bapp_connectors.providers.devops.gitlab.errors import GitLabNotFoundError
from bapp_connectors.providers.devops.gitlab.manifest import manifest
from bapp_connectors.providers.devops.gitlab.mappers import (
    issue_draft_to_payload,
    map_commit,
    map_issue,
    map_issue_comment,
    map_merge_request,
    map_pipeline,
    map_repository,
    webhook_event_from_gitlab,
)

if TYPE_CHECKING:
    from datetime import datetime

WEBHOOK_TOKEN_HEADER = "x-gitlab-token"


def _page(items: list, cursor: str | None, total: int | None = None) -> PaginatedResult:
    return PaginatedResult(items=items, cursor=cursor, has_more=cursor is not None, total=total)


class GitLabAdapter(DevOpsPort, IssueManagementCapability, WebhookCapability):
    """One GitLab server (gitlab.com or self-managed) reached with an access token.

    Methods accept a project's numeric id or its `group/path` as `ref`; the `ref` carried by
    every returned DTO (Repository, Issue, MergeRequest, Commit, Pipeline) is always the numeric id.
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials or {}
        config = config or {}

        self.host = str(self.credentials.get("host", "")).strip().rstrip("/")
        self.token = str(self.credentials.get("token", ""))
        self.webhook_secret = str(self.credentials.get("webhook_secret") or "")
        self.verify_ssl = bool(config.get("verify_ssl", True))
        self.timeout = int(config.get("timeout", 30))
        self.groups = [g.strip() for g in str(config.get("groups") or "").split(",") if g.strip()]
        self.include_archived = bool(config.get("include_archived", False))

        # As with cPanel: an injected client (from `registry.create_adapter`) points at the
        # manifest's placeholder host with NoAuth, so GitLabClient sends absolute URLs and its
        # own token header; the HTTP client contributes only its retry policy and rate limiter.
        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=f"https://{self.host}/",
                retry_policy=RetryPolicy(
                    max_retries=manifest.retry.max_retries,
                    backoff=manifest.retry.backoff,
                    base_delay=manifest.retry.base_delay,
                    max_delay=manifest.retry.max_delay,
                    retryable_status_codes=set(manifest.retry.retryable_status_codes),
                    non_retryable_status_codes=set(manifest.retry.non_retryable_status_codes),
                ),
                rate_limiter=RateLimiter(
                    requests_per_second=manifest.rate_limit.requests_per_second,
                    burst=manifest.rate_limit.burst,
                ),
                timeout=self.timeout,
                provider_name="gitlab",
            )
        self.http_client = http_client

        self.client = GitLabClient(
            http_client=http_client,
            host=self.host,
            token=self.token,
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        """`GET /user`; project and group tokens get 403 there, so fall back to `GET /version`."""
        try:
            try:
                user = self.client.get_user() or {}
            except GitLabNotFoundError:
                version = self.client.get_version() or {}
                return ConnectionTestResult(
                    success=True, message="Connected.", details={"version": version.get("version", "")}
                )
        except ConnectorError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(
            success=True,
            message="Connected.",
            details={"username": user.get("username", ""), "name": user.get("name", "")},
        )

    # ── DevOpsPort ──

    def list_projects(self, search: str | None = None, cursor: str | None = None) -> PaginatedResult[Repository]:
        """Projects of the configured groups (subgroups included), or every project the token is a member of.

        Pages have no guaranteed minimum size: with groups set, a group without projects still
        yields an empty page whose cursor moves on to the next group. Stop on `has_more=False`,
        never on empty `items`. `total` is reported only without groups (it would be per group).

        A stored cursor that no longer fits the configured groups (or is malformed) raises
        `ValidationError`: the caller drops it and restarts with `cursor=None`.
        """
        items, next_cursor = self.client.list_projects(cursor, search, self.groups, self.include_archived)
        total = None if self.groups else self.client.last_total
        return _page([map_repository(raw) for raw in items], next_cursor, total)

    def get_project(self, ref: str) -> Repository:
        return map_repository(self.client.get_project(ref))

    def list_issues(
        self, ref: str, state: str = "opened", since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[Issue]:
        items, next_page = self.client.list_issues(ref, state, since, cursor)
        return _page([map_issue(raw) for raw in items], next_page)

    def get_issue(self, ref: str, number: int) -> Issue:
        return map_issue(self.client.get_issue(ref, number))

    def list_merge_requests(
        self, ref: str, state: str = "opened", since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[MergeRequest]:
        items, next_page = self.client.list_merge_requests(ref, state, since, cursor)
        return _page([map_merge_request(raw) for raw in items], next_page)

    def list_commits(
        self, ref: str, branch: str | None = None, since: datetime | None = None, cursor: str | None = None
    ) -> PaginatedResult[Commit]:
        items, next_page = self.client.list_commits(ref, branch, since, cursor)
        project_id = self._project_id(ref)
        return _page([map_commit(raw, project_id) for raw in items], next_page)

    def list_pipelines(
        self, ref: str, branch: str | None = None, cursor: str | None = None
    ) -> PaginatedResult[Pipeline]:
        items, next_page = self.client.list_pipelines(ref, branch, cursor)
        project_id = self._project_id(ref)
        return _page([map_pipeline(raw, project_id) for raw in items], next_page)

    def _project_id(self, ref: str) -> str:
        """The numeric id for DTOs: `ref` itself when already numeric, else one `GET /projects/:path`."""
        ref = str(ref)
        if ref.isdigit():
            return ref
        return map_repository(self.client.get_project(ref)).ref

    # ── IssueManagementCapability ──

    def create_issue(self, ref: str, draft: IssueDraft) -> Issue:
        return map_issue(self.client.create_issue(ref, issue_draft_to_payload(draft)))

    def update_issue(self, ref: str, number: int, draft: IssueDraft) -> Issue:
        return map_issue(self.client.update_issue(ref, number, issue_draft_to_payload(draft)))

    def close_issue(self, ref: str, number: int) -> Issue:
        return map_issue(self.client.update_issue(ref, number, {"state_event": "close"}))

    def reopen_issue(self, ref: str, number: int) -> Issue:
        return map_issue(self.client.update_issue(ref, number, {"state_event": "reopen"}))

    def add_issue_comment(self, ref: str, number: int, body: str) -> IssueComment:
        return map_issue_comment(self.client.create_issue_note(ref, number, body))

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """GitLab sends the webhook's secret token as-is in `X-Gitlab-Token` (no HMAC over the body)."""
        expected = secret or self.webhook_secret
        received = next(
            (str(v or "") for k, v in (headers or {}).items() if str(k).lower() == WEBHOOK_TOKEN_HEADER), ""
        )
        if not expected or not received:
            return False
        return hmac.compare_digest(received.encode(), expected.encode())

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        return webhook_event_from_gitlab(headers, json.loads(body or b"{}"))

    def register_webhook(self, url: str, events: list[str] | None = None, *, ref: str = "") -> dict:
        """Create a project hook on `ref` for push, issue, merge request, pipeline and note events.

        `events` is ignored: every event the manifest maps is subscribed. `webhook_secret` is
        required: without it GitLab would send no token and `verify_webhook` rejects every
        delivery. When the project already has a hook with the same `url`, nothing is created
        and that existing hook is returned (its secret and events are left as they are).
        """
        if not ref:
            raise ValidationError("ref is required")
        if not self.webhook_secret:
            raise ValidationError("webhook_secret is required to register a webhook")
        existing = next((hook for hook in self.client.list_hooks(ref) if hook.get("url") == url), None)
        if existing is not None:
            return existing
        payload = {
            "url": url,
            "token": self.webhook_secret,
            "push_events": True,
            "issues_events": True,
            "merge_requests_events": True,
            "pipeline_events": True,
            "note_events": True,
            "enable_ssl_verification": self.verify_ssl,
        }
        return self.client.create_hook(ref, payload)

    def list_webhooks(self, *, ref: str = "") -> list[dict]:
        if not ref:
            raise ValidationError("ref is required")
        return self.client.list_hooks(ref)
