"""
Resilient HTTP client with retry, rate limiting, auth strategies, and observability hooks.

Extracted and evolved from external_connectors/sdk/generic_client.py — zero Django dependencies.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import requests

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)
from bapp_connectors.core.http.auth import BaseAuthStrategy, NoAuth
from bapp_connectors.core.http.middleware import MiddlewareChain, RequestContext, ResponseContext
from bapp_connectors.core.http.retry import RetryPolicy, execute_with_retry

if TYPE_CHECKING:
    from bapp_connectors.core.http.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class ResilientHttpClient:
    """
    Base HTTP client with retry, rate limiting, and observability.

    Provider clients extend this class and configure auth, base_url, etc.
    """

    def __init__(
        self,
        base_url: str,
        auth: BaseAuthStrategy | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        timeout: int = 10,
        provider_name: str = "",
        middleware: MiddlewareChain | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.auth = auth or NoAuth()
        self.retry_policy = retry_policy
        self.rate_limiter = rate_limiter
        self.timeout = timeout
        self.provider_name = provider_name
        self.middleware = middleware or MiddlewareChain()
        self._session = requests.Session()

    def _build_url(self, path: str) -> str:
        """Build full URL from base + path. Handles absolute URLs."""
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(self.base_url, path.lstrip("/"))

    def _build_headers(self, extra_headers: dict | None = None) -> dict:
        """Build request headers with auth applied."""
        headers = {}
        headers = self.auth.apply_to_headers(headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _classify_error(self, response: requests.Response) -> None:
        """Classify HTTP error responses into framework error types."""
        status = response.status_code

        if status == 401 or status == 403:
            raise AuthenticationError(
                f"Authentication failed: {status} {response.text[:200]}",
                status_code=status,
            )

        if status in (428, 429):
            retry_after = None
            if ra := response.headers.get("Retry-After"):
                with contextlib.suppress(ValueError):
                    retry_after = float(ra)
            raise RateLimitError(
                f"Rate limited: {status}",
                retry_after=retry_after,
            )

        if 400 <= status < 500:
            raise PermanentProviderError(
                f"Client error: {status} {response.text[:500]}",
                status_code=status,
            )

        if status >= 500:
            raise ProviderError(
                f"Server error: {status} {response.text[:500]}",
                status_code=status,
            )

    def _process_response(self, response: requests.Response) -> dict | list | str:
        """Parse response body. Override in subclasses for custom parsing."""
        try:
            return response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            return response.text

    def _execute_request(
        self,
        method: str,
        path: str,
        direct_response: bool = False,
        headers: dict | None = None,
        **kwargs,
    ) -> requests.Response | dict | list | str:
        """Execute a single HTTP request (called by retry wrapper)."""
        # Rate limiting
        if self.rate_limiter:
            self.rate_limiter.wait()

        url = self._build_url(path)
        request_headers = self._build_headers(headers)

        # Set timeout
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        # Auth object (for Basic auth)
        auth_obj = self.auth.get_auth()
        if "auth" in kwargs:
            auth_obj = kwargs.pop("auth")

        req_ctx = RequestContext(
            method=method,
            url=url,
            headers=request_headers,
            kwargs=kwargs,
            started_at=time.monotonic(),
            provider=self.provider_name,
        )
        self.middleware.fire_on_request(req_ctx)

        try:
            response = self._session.request(
                method,
                url,
                headers=request_headers,
                auth=auth_obj,
                **kwargs,
            )
        except requests.RequestException as exc:
            self.middleware.fire_on_error(req_ctx, exc)
            raise

        duration_ms = int((time.monotonic() - req_ctx.started_at) * 1000)
        resp_ctx = ResponseContext(
            request=req_ctx,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        self.middleware.fire_on_response(resp_ctx)

        if direct_response:
            return response

        # Error classification (skipped for direct_response — caller handles status)
        if not response.ok:
            self._classify_error(response)

        return self._process_response(response)

    def call(
        self,
        method: str,
        path: str,
        direct_response: bool = False,
        headers: dict | None = None,
        **kwargs,
    ) -> requests.Response | dict | list | str:
        """
        Make an API call with retry and rate limiting.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            path: API path (relative to base_url, or absolute URL).
            direct_response: If True, return raw requests.Response.
            headers: Extra headers to merge.
            **kwargs: Passed to requests (json, data, params, timeout, etc.).
        """
        if self.retry_policy:
            return execute_with_retry(
                lambda: self._execute_request(method, path, direct_response, headers, **kwargs),
                retry_policy=self.retry_policy,
            )
        return self._execute_request(method, path, direct_response, headers, **kwargs)

    def get(self, path: str, **kwargs):
        return self.call("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.call("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.call("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.call("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.call("DELETE", path, direct_response=True, **kwargs)
