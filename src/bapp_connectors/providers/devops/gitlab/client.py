"""Raw GitLab REST v4 transport. No business logic, no DTOs — only HTTP and pagination."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import requests

from bapp_connectors.core.http.retry import execute_with_retry
from bapp_connectors.providers.devops.gitlab.errors import GitLabError, GitLabUnreachableError, raise_for_status

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bapp_connectors.core.http import ResilientHttpClient

PER_PAGE = 100


def encode_ref(ref: int | str) -> str:
    """A project/group ref is a numeric id or a `group/path`, which GitLab wants URL-encoded."""
    return quote(str(ref), safe="")


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _bool(value: bool) -> str:
    return "true" if value else "false"


class GitLabClient:
    """Calls `https://{host}/api/v4/...` with a `PRIVATE-TOKEN` header.

    The server and the token live here, not in the injected HTTP client: every request
    goes to an ABSOLUTE url and carries its own auth header. `registry.create_adapter`
    builds the HTTP client from the manifest's placeholder `base_url` with `NoAuth` for
    `AuthStrategy.CUSTOM`, so inheriting either would hit the placeholder host anonymously.

    Every request uses `direct_response=True` so pagination headers (`X-Next-Page`,
    `X-Total`) can be read; status codes are therefore checked here, not by the HTTP client.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        host: str,
        token: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        self.http = http_client
        self.host = host
        self.token = token
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    # ── transport ──

    def base_url(self) -> str:
        return f"https://{self.host}/api/v4/"

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        retry: bool = True,
    ) -> tuple[Any, Mapping[str, str]]:
        """Send one request; return `(parsed_json, response_headers)` or raise a mapped error.

        The HTTP client's retry policy wraps the call AND the status check: with
        `direct_response=True` the HTTP client returns a 429/5xx instead of raising, so its
        own retry loop would never see it. The inner call therefore runs with `retry=False`
        and the mapped error (RateLimitError, GitLabError, GitLabUnreachableError — all
        retryable) is raised inside the retried callable.

        Pass `retry=False` for non-idempotent writes (creates): a timeout after GitLab
        processed the request must not replay it.
        """
        url = f"{self.base_url()}{path.lstrip('/')}"
        kwargs: dict[str, Any] = {"timeout": self.timeout, "verify": self.verify_ssl}
        if params:
            kwargs["params"] = {k: v for k, v in params.items() if v is not None}
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
                headers={"PRIVATE-TOKEN": self.token},
                retry=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            # An HTTPError raised by the transport still carries the status: map it like any other.
            failed = getattr(exc, "response", None)
            if failed is not None and getattr(failed, "status_code", None):
                raise_for_status(failed.status_code, getattr(failed, "text", ""), url)
            # ResilientHttpClient re-raises transport failures unwrapped (DNS, refused
            # connection, TLS, timeout); left raw they escape the framework's hierarchy.
            raise GitLabUnreachableError(f"Could not reach {self.host}: {exc}") from exc

        raise_for_status(response.status_code, getattr(response, "text", ""), url)
        # Kept as-is: on a real response it is a case-insensitive mapping.
        headers = response.headers if response.headers is not None else {}
        if response.status_code == 204 or not getattr(response, "text", ""):
            return None, headers
        try:
            return response.json(), headers
        except ValueError as exc:
            raise GitLabError(f"GitLab answered with a non-JSON body: {url}") from exc

    def paged(self, path: str, params: dict | None) -> tuple[list, str | None]:
        """Fetch one page of a list endpoint; return its items and the next page (None on the last)."""
        query = {"per_page": PER_PAGE, **(params or {})}
        data, headers = self.request("GET", path, params=query)
        next_page = (headers.get("X-Next-Page") or headers.get("x-next-page") or "").strip()
        return list(data or []), next_page or None

    # ── endpoints ──

    def get_user(self) -> dict:
        return self.request("GET", "user")[0]

    def get_version(self) -> dict:
        return self.request("GET", "version")[0]

    def list_projects(
        self,
        page: str | None,
        search: str | None,
        groups: list[str],
        include_archived: bool,
    ) -> tuple[list[dict], str | None]:
        """One page of projects.

        Without groups the cursor is GitLab's page number. With groups it is
        `"{group_index}:{page}"`: each group is walked to its last page before the next one.
        """
        params: dict[str, Any] = {"order_by": "last_activity_at", "search": search or None}
        if not include_archived:
            params["archived"] = "false"

        if not groups:
            params["membership"] = "true"
            params["page"] = page
            return self.paged("projects", params)

        group_index, group_page = 0, None
        if page:
            index, _, number = page.partition(":")
            group_index, group_page = int(index), number or None
        params["include_subgroups"] = "true"
        params["page"] = group_page
        items, next_page = self.paged(f"groups/{encode_ref(groups[group_index])}/projects", params)
        if next_page:
            return items, f"{group_index}:{next_page}"
        if group_index + 1 < len(groups):
            return items, f"{group_index + 1}:1"
        return items, None

    def get_project(self, ref: int | str) -> dict:
        return self.request("GET", f"projects/{encode_ref(ref)}")[0]

    def list_issues(
        self,
        ref: int | str,
        state: str | None,
        updated_after: datetime | str | None,
        page: str | None,
    ) -> tuple[list[dict], str | None]:
        params = {
            "state": state,
            "updated_after": _iso(updated_after),
            "order_by": "updated_at",
            "sort": "desc",
            "page": page,
        }
        return self.paged(f"projects/{encode_ref(ref)}/issues", params)

    def get_issue(self, ref: int | str, iid: int | str) -> dict:
        return self.request("GET", f"projects/{encode_ref(ref)}/issues/{iid}")[0]

    def list_merge_requests(
        self,
        ref: int | str,
        state: str | None,
        updated_after: datetime | str | None,
        page: str | None,
    ) -> tuple[list[dict], str | None]:
        params = {
            "state": state,
            "updated_after": _iso(updated_after),
            "order_by": "updated_at",
            "sort": "desc",
            "page": page,
        }
        return self.paged(f"projects/{encode_ref(ref)}/merge_requests", params)

    def list_commits(
        self,
        ref: int | str,
        ref_name: str | None,
        since: datetime | str | None,
        page: str | None,
    ) -> tuple[list[dict], str | None]:
        params = {"ref_name": ref_name, "since": _iso(since), "page": page}
        return self.paged(f"projects/{encode_ref(ref)}/repository/commits", params)

    def list_pipelines(
        self,
        ref: int | str,
        ref_name: str | None,
        page: str | None,
    ) -> tuple[list[dict], str | None]:
        params = {"ref": ref_name, "order_by": "id", "sort": "desc", "page": page}
        return self.paged(f"projects/{encode_ref(ref)}/pipelines", params)

    def create_issue(self, ref: int | str, data: dict) -> dict:
        return self.request("POST", f"projects/{encode_ref(ref)}/issues", json=data, retry=False)[0]

    def update_issue(self, ref: int | str, iid: int | str, data: dict) -> dict:
        return self.request("PUT", f"projects/{encode_ref(ref)}/issues/{iid}", json=data)[0]

    def create_issue_note(self, ref: int | str, iid: int | str, body: str) -> dict:
        return self.request("POST", f"projects/{encode_ref(ref)}/issues/{iid}/notes", json={"body": body}, retry=False)[
            0
        ]

    def create_hook(self, ref: int | str, data: dict) -> dict:
        return self.request("POST", f"projects/{encode_ref(ref)}/hooks", json=data, retry=False)[0]

    def list_hooks(self, ref: int | str) -> list[dict]:
        return list(self.request("GET", f"projects/{encode_ref(ref)}/hooks", params={"per_page": PER_PAGE})[0] or [])
