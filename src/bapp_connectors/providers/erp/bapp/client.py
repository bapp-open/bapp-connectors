"""
BAPP ERP client: raw task calls only.

A BAPP task is ``POST <base>tasks/<code>`` with the task options as JSON. A DirectTask answers
HTTP 200 with ``{"finished": bool, "message": str, "failed": bool, "data": dict}`` (see
``DirectTaskInterface.perform_action`` in the ERP): a refused task is ``failed: true`` with the
reason in ``message``, still with HTTP 200. Print and SMS are not idempotent, so nothing here is
retried, and a timeout on them is reported as an unknown outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

from bapp_connectors.providers.erp.bapp.errors import BappErpAuthError, BappErpError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

TASK_CAPABILITIES = "company_device.BappCapabilities"
TASK_PRINT = "company_device.PrintFile"
TASK_SEND_SMS = "company_sms.SendSms"


class _Secret:
    """Holds the token so it does not show in a repr, a vars() dump or a traceback."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value or ""

    def get(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<secret>"

    __str__ = __repr__


class BappErpApiClient:
    def __init__(self, http_client: ResilientHttpClient, token: str, base_url: str):
        self.http = http_client
        self._token = _Secret(token)
        self.base_url = base_url.rstrip("/") + "/"

    def __repr__(self) -> str:
        return f"BappErpApiClient(base_url={self.base_url!r})"

    def _headers(self) -> dict:
        # Set here, not left to the http client's auth: the registry builds that with a bare
        # token and BAPP wants "Token <uuid>". No X-Tenant-Id: the token is bound to one company
        # and BAPP takes the company from it.
        return {
            "Authorization": f"Token {self._token.get()}",
            "Content-Type": "application/json",
        }

    def run_task(self, code: str, options: dict | None = None, idempotent: bool = True) -> dict:
        """Run a task and return its ``data`` dict. Raises BappErpError on any failure.

        ``idempotent=False`` (print, SMS) makes a read timeout say the outcome is unknown: the
        ERP may have queued the job already, so the caller must not resend it on its own.
        """
        try:
            response = self.http.call(
                "POST",
                f"{self.base_url}tasks/{code}",
                direct_response=True,
                retry=False,
                headers=self._headers(),
                json=options or {},
            )
        except requests.ConnectTimeout:
            # never reached the server: nothing was sent
            raise BappErpError("BAPP is unreachable (ConnectTimeout)") from None
        except requests.Timeout:
            if idempotent:
                raise BappErpError("BAPP nu a raspuns la timp") from None
            raise BappErpError("BAPP nu a raspuns la timp; nu se stie daca s-a trimis — nu retrimite automat") from None
        except requests.RequestException as exc:
            raise BappErpError(f"BAPP is unreachable ({type(exc).__name__})") from None

        status = response.status_code
        if status in (401, 403):
            raise BappErpAuthError(f"BAPP rejected the credentials (HTTP {status})", status_code=status)

        try:
            body = response.json()
        except ValueError:
            body = None
        message = _message(body)

        if not 200 <= status < 300:
            raise BappErpError(
                message or f"BAPP error (HTTP {status}): {(response.text or '')[:300]}", status_code=status
            )
        if not isinstance(body, dict):
            raise BappErpError(f"Unexpected BAPP response (HTTP {status})", status_code=status)
        # The ERP's wire key is ``failed``; ``success`` is accepted too. Neither one present means
        # this is not a task answer we understand: fail closed rather than report a print/SMS
        # that may not have happened.
        if body.get("failed") is True or body.get("success") is False:
            raise BappErpError(message or "BAPP task failed", status_code=status)
        if body.get("failed") is not False and body.get("success") is not True:
            raise BappErpError(f"Unexpected BAPP response (HTTP {status})", status_code=status)
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def get_capabilities(self) -> dict:
        return self.run_task(TASK_CAPABILITIES)

    def print_file(self, url: str, device: str, printer: str, copies: int) -> dict:
        return self.run_task(
            TASK_PRINT, {"url": url, "device": device, "printer": printer, "copies": copies}, idempotent=False
        )

    def send_sms(self, recipients: list[str], body: str, phone: str) -> dict:
        return self.run_task(TASK_SEND_SMS, {"recipients": recipients, "body": body, "phone": phone}, idempotent=False)


def _message(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return ""
