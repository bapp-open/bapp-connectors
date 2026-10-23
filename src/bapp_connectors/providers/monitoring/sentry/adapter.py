"""Sentry adapter — MonitoringPort, issue triage and integration webhooks over REST api/0."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import IssueTriageCapability, WebhookCapability
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult, WebhookEvent
from bapp_connectors.core.dto.monitoring import ErrorIssue, MonitoredProject, MonitoredProjectStats
from bapp_connectors.core.errors import ConnectorError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.rate_limit import RateLimiter
from bapp_connectors.core.http.retry import RetryPolicy
from bapp_connectors.core.ports import MonitoringPort
from bapp_connectors.core.webhooks.signatures import HmacSha256Verifier
from bapp_connectors.providers.monitoring.sentry.client import SentryClient
from bapp_connectors.providers.monitoring.sentry.manifest import manifest
from bapp_connectors.providers.monitoring.sentry.mappers import (
    map_issue,
    map_project,
    map_stats,
    webhook_event_from_sentry,
)

if TYPE_CHECKING:
    from datetime import datetime

WEBHOOK_SIGNATURE_HEADER = "sentry-hook-signature"


def _page(items: list, cursor: str | None) -> PaginatedResult:
    return PaginatedResult(items=items, cursor=cursor, has_more=cursor is not None)


class SentryAdapter(MonitoringPort, IssueTriageCapability, WebhookCapability):
    """One Sentry organization (sentry.io or self-hosted) reached with an auth token.

    The `ref` of every project-scoped call, and of every returned DTO, is the project slug.
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
        self.organization = str(self.credentials.get("organization", "")).strip()
        self.token = str(self.credentials.get("token", ""))
        self.webhook_secret = str(self.credentials.get("webhook_secret") or "")
        self.verify_ssl = bool(config.get("verify_ssl", True))
        self.timeout = int(config.get("timeout", 30))
        self.stats_period = str(config.get("stats_period") or "14d").strip()
        self.environment = str(config.get("environment") or "").strip()

        # As with GitLab: an injected client (from `registry.create_adapter`) points at the
        # manifest's placeholder host with NoAuth, so SentryClient sends absolute URLs and its
        # own Bearer header; the HTTP client contributes only its retry policy and rate limiter.
        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=f"https://{self.host}/api/0/",
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
                provider_name="sentry",
            )
        self.http_client = http_client

        self.client = SentryClient(
            http_client=http_client,
            host=self.host,
            organization=self.organization,
            token=self.token,
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        """`GET /organizations/:org/`: proves the host, the organization slug and the token at once."""
        try:
            org = self.client.get_organization() or {}
        except ConnectorError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(
            success=True,
            message="Connected.",
            details={"organization": org.get("slug", ""), "name": org.get("name", "")},
        )

    # ── MonitoringPort ──

    def list_projects(self, cursor: str | None = None) -> PaginatedResult[MonitoredProject]:
        items, next_cursor = self.client.list_projects(cursor)
        return _page([map_project(raw, self.host, self.organization) for raw in items], next_cursor)

    def get_project(self, ref: str) -> MonitoredProject:
        return map_project(self.client.get_project(ref), self.host, self.organization)

    def list_issues(
        self,
        ref: str,
        query: str = "is:unresolved",
        period: str = "14d",
        sort: str = "date",
        cursor: str | None = None,
    ) -> PaginatedResult[ErrorIssue]:
        """Issues of project `ref`, filtered by the configured `environment` when one is set.

        `period` is used as given: the configured `stats_period` is the default the caller
        passes in, it never overrides an explicit argument here.
        """
        items, next_cursor = self.client.list_issues(ref, query, period, sort, self.environment or None, cursor)
        return _page([map_issue(raw) for raw in items], next_cursor)

    def get_issue(self, issue_id: str) -> ErrorIssue:
        return map_issue(self.client.get_issue(issue_id))

    def get_project_stats(self, ref: str, period: str = "24h") -> MonitoredProjectStats:
        """Error outcomes of project `ref`; stats_v2 wants the numeric id, so the slug is resolved first."""
        project_id = (self.client.get_project(ref) or {}).get("id")
        return map_stats(self.client.project_stats(project_id, period), ref, period)

    # ── IssueTriageCapability ──

    def resolve_issue(self, issue_id: str) -> ErrorIssue:
        return map_issue(self.client.update_issue(issue_id, {"status": "resolved"}))

    def unresolve_issue(self, issue_id: str) -> ErrorIssue:
        return map_issue(self.client.update_issue(issue_id, {"status": "unresolved"}))

    def ignore_issue(self, issue_id: str, until: datetime | None = None) -> ErrorIssue:
        details = {"ignoreUntil": until.isoformat()} if until else {}
        return map_issue(self.client.update_issue(issue_id, {"status": "ignored", "statusDetails": details}))

    def assign_issue(self, issue_id: str, email: str) -> ErrorIssue:
        return map_issue(self.client.update_issue(issue_id, {"assignedTo": email}))

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Hex HMAC-SHA256 of the raw body with the integration's client secret, in `Sentry-Hook-Signature`.

        False (never an exception) when no secret is configured or the header is missing.
        """
        expected_secret = secret or self.webhook_secret
        signature = next(
            (str(v or "") for k, v in (headers or {}).items() if str(k).lower() == WEBHOOK_SIGNATURE_HEADER), ""
        )
        if not expected_secret or not signature:
            return False
        return HmacSha256Verifier().verify(body or b"", signature, expected_secret)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        return webhook_event_from_sentry(headers, json.loads(body or b"{}"))

    # `register_webhook` / `list_webhooks` stay the base NotImplementedError: Sentry webhooks
    # are configured on the internal integration, not through the API.
