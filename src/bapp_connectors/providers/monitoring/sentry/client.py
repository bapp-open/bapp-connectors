"""Raw Sentry REST (api/0) transport. No business logic, no DTOs — only HTTP and pagination."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import requests

from bapp_connectors.core.http.retry import execute_with_retry
from bapp_connectors.providers.monitoring.sentry.errors import (
    SentryError,
    SentryUnreachableError,
    raise_for_status,
    reject_internal_error,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bapp_connectors.core.http import ResilientHttpClient

_LINK_PARAM = re.compile(r'(\w+)="([^"]*)"')


def parse_next_cursor(link_header: str | None) -> str | None:
    """The cursor of the next page from Sentry's `Link` header, or None on the last page.

    Sentry always sends a `rel="next"` entry; it only points at real rows when that
    entry also says `results="true"`.
    """
    for entry in (link_header or "").split(","):
        attrs = dict(_LINK_PARAM.findall(entry))
        if attrs.get("rel") == "next":
            if attrs.get("results") == "true" and attrs.get("cursor"):
                return attrs["cursor"]
            return None
    return None


class SentryClient:
    """Calls `https://{host}/api/0/...` with an `Authorization: Bearer` header.

    The server and the token live here, not in the injected HTTP client: every request
    goes to an ABSOLUTE url and carries its own auth header. `registry.create_adapter`
    builds the HTTP client from the manifest's placeholder `base_url` with `NoAuth` for
    `AuthStrategy.CUSTOM`, so inheriting either would hit the placeholder host anonymously.

    Every request uses `direct_response=True` so the `Link` pagination header can be read;
    status codes are therefore checked here, not by the HTTP client.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        host: str,
        organization: str,
        token: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        self.http = http_client
        self.host = host
        self.organization = organization
        self.token = token
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    # ── transport ──

    def base_url(self) -> str:
        return f"https://{self.host}/api/0/"

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        retry: bool = True,
    ) -> tuple[Any, Mapping[str, str]]:
        """Send one request; return `(parsed_json, response_headers)` or raise a mapped error.

        The HTTP client's retry policy wraps the call, the status check AND the
        'Internal Error' body check: with `direct_response=True` the HTTP client returns a
        429/5xx instead of raising, so its own retry loop would never see it. The inner
        call therefore runs with `retry=False` and the mapped error (RateLimitError,
        SentryError, SentryUnreachableError — all retryable) is raised inside the retried
        callable.

        Pass `retry=False` for non-idempotent writes: a timeout after Sentry processed the
        request must not replay it.
        """
        url = f"{self.base_url()}{path.lstrip('/')}"
        kwargs: dict[str, Any] = {"timeout": self.timeout, "verify": self.verify_ssl}
        kwargs["params"] = {k: v for k, v in (params or {}).items() if v is not None}
        if json is not None:
            kwargs["json"] = json
        policy = getattr(self.http, "retry_policy", None) if retry else None
        return execute_with_retry(lambda: self._send(method.upper(), url, kwargs), retry_policy=policy)

    def _send(self, method: str, url: str, kwargs: dict[str, Any]) -> tuple[Any, Mapping[str, str]]:
        """One attempt: no retry here, the caller's policy decides."""
        try:
            response = self.http.call(
                method,
                url,
                direct_response=True,
                headers={"Authorization": f"Bearer {self.token}"},
                retry=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            # An HTTPError raised by the transport still carries the status: map it like any other.
            failed = getattr(exc, "response", None)
            if failed is not None and getattr(failed, "status_code", None):
                raise_for_status(failed.status_code, getattr(failed, "text", ""), url, getattr(failed, "headers", None))
            # ResilientHttpClient re-raises transport failures unwrapped (DNS, refused
            # connection, TLS, timeout); left raw they escape the framework's hierarchy.
            raise SentryUnreachableError(f"Could not reach {self.host}: {exc}") from exc

        raise_for_status(response.status_code, getattr(response, "text", ""), url, response.headers)
        # Kept as-is: on a real response it is a case-insensitive mapping.
        headers = response.headers if response.headers is not None else {}
        if response.status_code == 204 or not getattr(response, "text", ""):
            return None, headers
        try:
            payload = response.json()
        except ValueError as exc:
            raise SentryError(f"Sentry answered with a non-JSON body: {url}") from exc
        reject_internal_error(payload, url)
        return payload, headers

    def paged(self, path: str, params: dict | None, cursor: str | None) -> tuple[list, str | None]:
        """Fetch one page of a list endpoint; return its items and the next cursor (None on the last)."""
        data, headers = self.request("GET", path, params={**(params or {}), "cursor": cursor})
        if not isinstance(data, list):
            raise SentryError(f"Sentry answered a list endpoint with {type(data).__name__}: {path}")
        link = headers.get("Link") or headers.get("link") or ""
        return data, parse_next_cursor(link)

    # ── endpoints ──

    def get_organization(self) -> dict:
        return self.request("GET", f"organizations/{self.organization}/")[0]

    def list_projects(self, cursor: str | None) -> tuple[list[dict], str | None]:
        return self.paged(f"organizations/{self.organization}/projects/", None, cursor)

    def get_project(self, slug: str) -> dict:
        return self.request("GET", f"projects/{self.organization}/{slug}/")[0]

    def list_issues(
        self,
        slug: str,
        query: str | None,
        stats_period: str | None,
        sort: str | None,
        environment: str | None,
        cursor: str | None,
    ) -> tuple[list[dict], str | None]:
        params = {
            "query": query,
            "statsPeriod": stats_period or None,
            "sort": sort or None,
            "environment": environment or None,
        }
        return self.paged(f"projects/{self.organization}/{slug}/issues/", params, cursor)

    def get_issue(self, issue_id: int | str) -> dict:
        return self.request("GET", f"issues/{issue_id}/")[0]

    def update_issue(self, issue_id: int | str, data: dict) -> dict:
        # PUT with the full new state is idempotent: replaying it after a timeout is harmless.
        return self.request("PUT", f"issues/{issue_id}/", json=data)[0]

    def project_stats(self, project_id: int | str, stats_period: str) -> dict:
        """Error outcomes (accepted, filtered, rate_limited, ...) of one project; `project_id` is numeric."""
        params = {
            "field": "sum(quantity)",
            "groupBy": "outcome",
            "category": "error",
            "project": project_id,
            "statsPeriod": stats_period,
        }
        return self.request("GET", f"organizations/{self.organization}/stats_v2/", params=params)[0]
