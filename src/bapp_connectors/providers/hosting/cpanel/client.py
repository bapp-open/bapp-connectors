"""Raw UAPI transport. No business logic, no DTOs — only HTTP and the envelope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bapp_connectors.providers.hosting.cpanel.errors import CpanelError, classify_uapi_error
from bapp_connectors.providers.hosting.cpanel.models import UapiEnvelope

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class CpanelUapiClient:
    """Calls `/execute/{Module}/{function}` and unwraps the UAPI envelope.

    Reads go over GET with a query string; writes go over POST with a form body so
    that passwords never reach a URL, and therefore never reach an access log.
    """

    def __init__(self, http_client: ResilientHttpClient, timeout: int = 30, verify_ssl: bool = True):
        self.http = http_client
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def call(self, module: str, function: str, method: str = "GET", **params: Any) -> Any:
        """Call a UAPI function and return its `data`.

        Raises a mapped framework error when the envelope reports `status != 1`,
        regardless of the HTTP status — a failed UAPI call is still HTTP 200.
        """
        payload = {k: v for k, v in params.items() if v is not None}
        path = f"execute/{module}/{function}"

        kwargs: dict[str, Any] = {"timeout": self.timeout, "verify": self.verify_ssl}
        if method.upper() == "GET":
            kwargs["params"] = payload
        else:
            kwargs["data"] = payload

        raw = self.http.call(method.upper(), path, **kwargs)
        if not isinstance(raw, dict):
            raise CpanelError(f"Unexpected UAPI response type: {type(raw).__name__}")

        envelope = UapiEnvelope.model_validate(raw)
        if not envelope.ok:
            raise classify_uapi_error(envelope.first_error)
        return envelope.data
