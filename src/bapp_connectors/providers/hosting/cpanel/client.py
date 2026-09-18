"""Raw UAPI transport. No business logic, no DTOs — only HTTP and the envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

from bapp_connectors.providers.hosting.cpanel.errors import (
    CpanelError,
    CpanelUnreachableError,
    classify_uapi_error,
)
from bapp_connectors.providers.hosting.cpanel.models import UapiEnvelope

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class CpanelUapiClient:
    """Calls `/execute/{Module}/{function}` and unwraps the UAPI envelope.

    The server and the credentials live here, not in the injected HTTP client:
    every request is sent to an ABSOLUTE url and carries its own `Authorization`
    header. `registry.create_adapter` always hands an adapter a client built from
    the manifest's placeholder `base_url`, and for `AuthStrategy.CUSTOM` it builds
    that client with `NoAuth` — inheriting either one silently sends every request
    to the placeholder host with no credentials.

    Reads go over GET with a query string; writes go over POST with a form body so
    that passwords never reach a URL, and therefore never reach an access log.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        hostname: str,
        username: str,
        token: str,
        port: int = 2083,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        self.http = http_client
        self.hostname = hostname
        self.username = username
        self.token = token
        self.port = port
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def base_url(self) -> str:
        return f"https://{self.hostname}:{self.port}/"

    def build_url(self, module: str, function: str) -> str:
        return f"{self.base_url()}execute/{module}/{function}"

    def auth_header(self) -> str:
        return f"cpanel {self.username}:{self.token}"

    def call(self, module: str, function: str, method: str = "GET", **params: Any) -> Any:
        """Call a UAPI function and return its `data`.

        Raises a mapped framework error when the envelope reports `status != 1`,
        regardless of the HTTP status — a failed UAPI call is still HTTP 200.
        """
        payload = {k: v for k, v in params.items() if v is not None}

        kwargs: dict[str, Any] = {
            "headers": {"Authorization": self.auth_header()},
            "timeout": self.timeout,
            "verify": self.verify_ssl,
        }
        if method.upper() == "GET":
            kwargs["params"] = payload
        else:
            kwargs["data"] = payload

        url = self.build_url(module, function)
        try:
            raw = self.http.call(method.upper(), url, **kwargs)
        except requests.RequestException as exc:
            # ResilientHttpClient re-raises transport failures unwrapped (DNS, refused
            # connection, TLS, timeout). Left raw they escape the framework's error
            # hierarchy and surface as a 500 in the host application.
            raise CpanelUnreachableError(f"Could not reach {self.hostname}: {exc}") from exc
        if not isinstance(raw, dict):
            raise CpanelError(f"Unexpected UAPI response type: {type(raw).__name__}")

        envelope = UapiEnvelope.model_validate(raw)
        if not envelope.ok:
            raise classify_uapi_error(envelope.first_error)
        return envelope.data
