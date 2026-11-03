"""
SAGA Web client: raw HTTP calls only.

Every request carries ``Authorization: Bearer <key>`` and ``X-Saga-Cod-Fiscal``. SAGA may hand
out a new key in ``X-Saga-Refresh-Token`` on any response, errors included; the old key gets
blocked if the new one is not saved and reused, so the header is captured on every response
before any status handling and passed on to ``on_credentials_update`` straight away.

Import is not idempotent: it is never retried, and a read timeout on it is reported as an
unknown outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from bapp_connectors.providers.accounting.saga_web.errors import (
    SagaWebAuthError,
    SagaWebError,
    SagaWebValidationError,
)
from bapp_connectors.providers.accounting.saga_web.mappers import parse_envelope

if TYPE_CHECKING:
    from collections.abc import Callable

    from bapp_connectors.core.http import ResilientHttpClient

REFRESH_HEADER = "X-Saga-Refresh-Token"
CIF_HEADER = "X-Saga-Cod-Fiscal"
IMPORT_PATH = "Import"


class _Secret:
    """Holds the key so it does not show in a repr, a vars() dump or a traceback."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value or ""

    def get(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<secret>"

    __str__ = __repr__


class SagaWebApiClient:
    def __init__(
        self,
        http_client: ResilientHttpClient,
        token: str,
        cod_fiscal: str,
        base_url: str,
        on_credentials_update: Callable[[dict], None] | None = None,
    ):
        self.http = http_client
        self._token = _Secret(token)
        self.cod_fiscal = cod_fiscal
        self.base_url = base_url.rstrip("/")
        self.on_credentials_update = on_credentials_update

    def __repr__(self) -> str:
        return f"SagaWebApiClient(base_url={self.base_url!r}, cod_fiscal={self.cod_fiscal!r})"

    @property
    def token(self) -> str:
        return self._token.get()

    def _headers(self) -> dict:
        # Built per call from the current key: never the http client's auth, which would keep
        # sending a key SAGA has already replaced.
        return {"Authorization": f"Bearer {self._token.get()}", CIF_HEADER: self.cod_fiscal}

    def _capture_refresh(self, response) -> None:
        new = _header(response, REFRESH_HEADER).strip()
        if not new or new == self._token.get():
            return
        self._token = _Secret(new)
        if self.on_credentials_update is not None:
            self.on_credentials_update({"token": new})

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        files: dict | None = None,
        data: dict | None = None,
        retry: bool,
    ) -> requests.Response:
        kwargs = {}
        if params is not None:
            kwargs["params"] = params
        if files is not None:
            kwargs["files"] = files
        if data is not None:
            kwargs["data"] = data
        try:
            response = self.http.call(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                direct_response=True,
                headers=self._headers(),
                retry=retry,
                **kwargs,
            )
        except requests.ConnectTimeout:
            # never reached the server: nothing was sent
            raise SagaWebError("SAGA Web nu răspunde (ConnectTimeout)") from None
        except requests.Timeout:
            if path.strip("/") == IMPORT_PATH:
                raise SagaWebError(
                    "SAGA Web nu a răspuns la timp; nu se știe dacă fișierul a fost primit — nu retrimite automat"
                ) from None
            raise SagaWebError("SAGA Web nu a răspuns la timp") from None
        except requests.RequestException as exc:
            # the exception text may carry request details; only its type is reported
            raise SagaWebError(f"SAGA Web nu răspunde ({type(exc).__name__})") from None

        self._capture_refresh(response)

        status = response.status_code
        if status in (401, 403):
            raise SagaWebAuthError(f"SAGA Web a respins cheia API (HTTP {status})", status_code=status)
        return response

    def import_file(self, filename: str, content: bytes, auto_import: bool) -> requests.Response:
        return self._request(
            "POST",
            IMPORT_PATH,
            files={"file": (filename, content, "application/xml")},
            data={"importAutomat": "true" if auto_import else "false"},
            retry=False,
        )

    def get_json(self, path: str, params: dict) -> tuple[bool, str, str]:
        response = self._request("GET", path, params=params, retry=True)
        success, message, data = parse_envelope(response.text)
        status = response.status_code
        if status == 400:
            raise SagaWebValidationError(message or "SAGA Web a respins cererea (HTTP 400)", status_code=400)
        if not 200 <= status < 300:
            raise SagaWebError(message or f"SAGA Web a răspuns cu HTTP {status}", status_code=status)
        return success, message, data

    def get_xml(self, path: str, params: dict) -> str:
        response = self._request("GET", path, params=params, retry=True)
        status = response.status_code
        if status == 200:
            return response.text
        _, message, _ = parse_envelope(response.text)
        message = message or f"SAGA Web a răspuns cu eroare (HTTP {status})"
        if status == 400:
            raise SagaWebValidationError(message, status_code=status)
        raise SagaWebError(message, status_code=status)


def _header(response, name: str) -> str:
    headers = getattr(response, "headers", None) or {}
    value = headers.get(name)
    if value is None:
        # requests gives a CaseInsensitiveDict; a plain dict (tests, other transports) may not be
        lowered = name.lower()
        for key, candidate in headers.items():
            if isinstance(key, str) and key.lower() == lowered:
                value = candidate
                break
    return value if isinstance(value, str) else ""
