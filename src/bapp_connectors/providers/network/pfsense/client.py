"""Raw XML-RPC transport for pfSense (`pfsense.exec_php`) with multi-endpoint failover.

Only HTTP here: no config parsing, no DTOs. The PHP snippets live in the adapter.
"""

from __future__ import annotations

import json
import xmlrpc.client
from typing import TYPE_CHECKING, Any

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConfigurationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)
from bapp_connectors.providers.network.pfsense.errors import (
    PfSenseError,
    PfSenseFaultError,
    PfSenseUnreachableError,
)

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

XMLRPC_PATH = "xmlrpc.php"
_HEADERS = {"Content-Type": "text/xml"}


def build_exec_php_body(code: str) -> str:
    safe = code.replace("]]>", "]]]]><![CDATA[>")
    return (
        '<?xml version="1.0"?>'
        "<methodCall><methodName>pfsense.exec_php</methodName>"
        "<params><param><value><string><![CDATA[\n"
        f"{safe}\n"
        "]]></string></value></param></params></methodCall>"
    )


def parse_response(text: str) -> Any:
    try:
        params, _method = xmlrpc.client.loads(text)
    except xmlrpc.client.Fault as fault:
        raise PfSenseFaultError(fault.faultString, fault_code=fault.faultCode) from fault
    except Exception as exc:  # malformed XML, HTML login page, ...
        raise PfSenseError(f"Unexpected XML-RPC response: {text[:200]!r}") from exc
    return params[0] if params else None


def _normalize(endpoint: str) -> str:
    return endpoint.strip().rstrip("/")


class PfSenseClient:
    """Sends `pfsense.exec_php` calls, trying endpoints in order until one answers."""

    def __init__(
        self,
        http_client: ResilientHttpClient,
        endpoints: list[str],
        verify_ssl: bool = False,
        timeout: int = 20,
    ):
        self.http = http_client
        self.endpoints = [_normalize(e) for e in endpoints if e and e.strip()]
        if not self.endpoints:
            raise ConfigurationError("pfSense: at least one endpoint URL is required")
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.active_endpoint: str | None = None

    # -- transport -----------------------------------------------------------------

    def _ordered_endpoints(self) -> list[str]:
        if self.active_endpoint and self.active_endpoint in self.endpoints:
            rest = [e for e in self.endpoints if e != self.active_endpoint]
            return [self.active_endpoint, *rest]
        return list(self.endpoints)

    def _post(self, endpoint: str, body: str) -> str:
        response = self.http.call(
            "POST",
            f"{endpoint}/{XMLRPC_PATH}",
            headers=dict(_HEADERS),
            data=body.encode("utf-8"),
            verify=self.verify_ssl,
            timeout=self.timeout,
            retry=False,
        )
        if isinstance(response, bytes):
            return response.decode("utf-8", errors="replace")
        if not isinstance(response, str):
            raise PfSenseError(f"Unexpected response type from pfSense: {type(response).__name__}")
        return response

    def exec_php(self, code: str) -> Any:
        body = build_exec_php_body(code)
        failures: list[tuple[str, str]] = []
        for endpoint in self._ordered_endpoints():
            try:
                text = self._post(endpoint, body)
            except (AuthenticationError, PermanentProviderError, RateLimitError):
                raise  # the box answered; another address will answer the same
            except (ProviderError, OSError) as exc:  # 5xx, timeouts, refused, DNS
                failures.append((endpoint, str(exc)))
                continue
            self.active_endpoint = endpoint
            return parse_response(text)
        detail = "; ".join(f"{ep}: {err}" for ep, err in failures)
        raise PfSenseUnreachableError(
            f"pfSense unreachable on all endpoints ({detail})",
            attempts=[ep for ep, _ in failures],
        )

    # -- convenience ---------------------------------------------------------------

    def run(self, php: str) -> Any:
        """Run PHP statements ending in `return <value>;` and get the value back as JSON."""
        code = (
            "global $toreturn;\n"
            "$toreturn = json_encode((function () {\n"
            f"{php}\n"
            "})(), JSON_UNESCAPED_SLASHES);\n"
        )
        raw = self.exec_php(code)
        if raw is None or raw == "":
            raise PfSenseError("pfSense returned an empty result for exec_php")
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise PfSenseError(f"pfSense returned non-JSON payload: {str(raw)[:200]!r}") from exc
