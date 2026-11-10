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

from datetime import date
from typing import TYPE_CHECKING, Any, Literal, TypeVar

import requests

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.dto import (  # noqa: TC001 -- runtime: get_type_hints on the AI reads
    Article,
    StockLine,
    TrialBalanceLine,
)
from bapp_connectors.core.http.retry import execute_with_retry
from bapp_connectors.providers.accounting.saga_web.errors import (
    SagaWebAuthError,
    SagaWebCredentialsNotSaved,
    SagaWebError,
    SagaWebValidationError,
)
from bapp_connectors.providers.accounting.saga_web.mappers import (
    parse_article,
    parse_envelope,
    parse_stock_report,
    parse_trial_balance,
    read_envelope,
    saga_date,
    to_decimal,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from decimal import Decimal

    from bapp_connectors.core.http import ResilientHttpClient

T = TypeVar("T")

REFRESH_HEADER = "X-Saga-Refresh-Token"
CIF_HEADER = "X-Saga-Cod-Fiscal"
IMPORT_PATH = "Import"
# Import waits for SAGA to process the whole file; reads keep the http client's default
IMPORT_TIMEOUT = 180
# SAGA answers 400 "Nu ati trimis un cod de articol valid" for an unknown article code
INVALID_ARTICLE_HINT = "cod de articol"


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
        # a pasted key often carries a trailing newline, which requests refuses in a header
        self._token = _Secret((token or "").strip())
        self.cod_fiscal = (cod_fiscal or "").strip()
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
        # the local is named ``token`` so error trackers scrub it from captured frames
        token = _header(response, REFRESH_HEADER).strip()
        if not token or token == self._token.get():
            return
        self._token = _Secret(token)
        if self.on_credentials_update is None:
            return
        try:
            self.on_credentials_update({"token": token})
        except Exception:
            del token
            raise SagaWebCredentialsNotSaved(
                "Cheia nouă SAGA Web nu a putut fi salvată; rularea trebuie oprită", retryable=False
            ) from None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        files: dict | None = None,
        data: dict | None = None,
        timeout: float | None = None,
    ) -> requests.Response:
        """One HTTP exchange, never replayed by the http client: under ``direct_response`` its
        retry only covers transport errors, and Import must not be replayed at all. Reads are
        retried as a whole by ``_read``."""
        # Import is not idempotent: none of its failures may be replayed by the host
        retryable = False if path.strip("/") == IMPORT_PATH else None
        kwargs = {}
        if params is not None:
            kwargs["params"] = params
        if files is not None:
            kwargs["files"] = files
        if data is not None:
            kwargs["data"] = data
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = self.http.call(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                direct_response=True,
                headers=self._headers(),
                retry=False,
                **kwargs,
            )
        except requests.ConnectTimeout:
            # never reached the server: nothing was sent
            raise SagaWebError("SAGA Web nu răspunde (ConnectTimeout)", retryable=retryable) from None
        except requests.Timeout:
            if retryable is False:
                raise SagaWebError(
                    "SAGA Web nu a răspuns la timp; nu se știe dacă fișierul a fost primit — nu retrimite automat",
                    retryable=False,
                ) from None
            raise SagaWebError("SAGA Web nu a răspuns la timp") from None
        except ValueError:
            # requests refuses a header value (a newline inside the pasted key or CIF) and quotes
            # the value in its message: only the type is reported
            raise SagaWebError("Credențiale SAGA Web invalide (ValueError)", retryable=False) from None
        except requests.RequestException as exc:
            # the exception text may carry request details; only its type is reported
            raise SagaWebError(f"SAGA Web nu răspunde ({type(exc).__name__})", retryable=retryable) from None

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
            timeout=IMPORT_TIMEOUT,
        )

    def _read(self, path: str, params: dict, handle: Callable[[requests.Response], T]) -> T:
        """GET ``path`` and ``handle`` the answer, retried whole under the http client's policy.

        Retrying the request together with its status check is what makes a 5xx or a 429 on a
        read retryable (``SagaWebError.retryable``); the key headers are rebuilt per attempt, so
        a key rotated by a failed attempt is the one the next attempt sends.
        """

        def attempt() -> T:
            return handle(self._request("GET", path, params=params))

        policy = getattr(self.http, "retry_policy", None)
        if policy is None:
            return attempt()
        return execute_with_retry(attempt, retry_policy=policy)

    def get_json(self, path: str, params: dict) -> tuple[bool, str, str]:
        """``(success, message, data)`` of SAGA's JSON envelope.

        A body that is not an envelope raises ``SagaWebError`` with ``is_envelope=False`` whatever
        the status, so a landing page answering 200 never reads as a SAGA answer.
        """
        return self._read(path, params, _json_answer)

    def get_xml(self, path: str, params: dict) -> str:
        return self._read(path, params, _xml_answer)

    # ── AI reads ──
    # Fixed SAGA "Situatii" endpoints, for an AI agent: the agent never picks the path. Each is a
    # GET that only reads a report; like every SAGA call it may rotate the key, which
    # ``_capture_refresh`` saves through ``on_credentials_update``.

    def _value(self, path: str, params: dict) -> Decimal:
        success, message, data = self.get_json(path, params)
        if not success:
            raise SagaWebError(
                message or "SAGA Web nu a returnat valoarea cerută", status_code=200, retryable=False, is_envelope=True
            )
        return _parsed(to_decimal, data, is_envelope=True)

    @ai_method("read", "Stock of one article on a day (today when day is omitted), optionally in one warehouse.")
    def get_article_stock(self, article_code: str, warehouse: str = "", day: date | None = None) -> dict:
        params = {"codArticol": article_code}
        if warehouse:
            params["gestiune"] = warehouse
        if day is not None:
            params["data"] = saga_date(day)
        stock = self._value("Situatii/GetStocArticol", params)
        return {"article_code": article_code, "warehouse": warehouse, "day": day, "stock": stock}

    @ai_method(
        "read", "Stock situation per warehouse and article between two dates (in, out, final quantities and values)."
    )
    def get_stock_report(self, start: date, end: date) -> list[StockLine]:
        xml = self.get_xml("Situatii/GetSituatieStocuri", {"dataStart": saga_date(start), "dataEnd": saga_date(end)})
        return _parsed(parse_stock_report, xml)

    @ai_method("read", "Balance of one account on a day (today when day is omitted); side D = debit, C = credit.")
    def get_account_balance(self, account: str, side: Literal["D", "C"], day: date | None = None) -> dict:
        day = day or date.today()
        balance = self._value("Situatii/GetSoldCont", {"cont": account, "tip": side, "data": saga_date(day)})
        return {"account": account, "side": side, "day": day, "balance": balance}

    @ai_method("read", "Trial balance between two dates; analytic=true lists analytic accounts too.")
    def get_trial_balance(self, start: date, end: date, analytic: bool = False) -> list[TrialBalanceLine]:
        params = {"dataStart": saga_date(start), "dataEnd": saga_date(end), "tipBalanta": "1" if analytic else "0"}
        return _parsed(parse_trial_balance, self.get_xml("Situatii/GetBalanta", params))

    @ai_method("read", "One article of the SAGA nomenclature by its code (name, VAT, unit, prices); null when unknown.")
    def get_article(self, article_code: str) -> Article | None:
        try:
            xml = self.get_xml("Situatii/GetArticol", {"codArticol": article_code})
        except SagaWebValidationError as exc:
            if INVALID_ARTICLE_HINT in str(exc).lower():
                return None
            raise
        return _parsed(parse_article, xml)


def _parsed(parser: Callable[[str], Any], text: str, *, is_envelope: bool = False) -> Any:
    """Run a mapper on a 2xx body; bad XML or a malformed number becomes a ``SagaWebError``."""
    try:
        return parser(text)
    except ValueError as exc:
        raise SagaWebError(
            f"Răspuns SAGA Web invalid: {exc}", status_code=200, retryable=False, is_envelope=is_envelope
        ) from None


def _retryable_status(status: int) -> bool:
    return status >= 500 or status == 429


def _json_answer(response) -> tuple[bool, str, str]:
    status = response.status_code
    envelope = read_envelope(response.text or "")
    if envelope is None:
        raise SagaWebError(
            f"SAGA Web a răspuns cu HTTP {status} fără un răspuns JSON",
            status_code=status,
            retryable=_retryable_status(status),
        )
    success, message, data = envelope
    if status == 400:
        raise SagaWebValidationError(
            message or "SAGA Web a respins cererea (HTTP 400)", status_code=400, is_envelope=True
        )
    if not 200 <= status < 300:
        raise SagaWebError(
            message or f"SAGA Web a răspuns cu HTTP {status}",
            status_code=status,
            is_envelope=True,
            retryable=_retryable_status(status),
        )
    return success, message, data


def _xml_answer(response) -> str:
    status = response.status_code
    if status == 200:
        return response.text
    _, message, _ = parse_envelope(response.text)
    message = message or f"SAGA Web a răspuns cu eroare (HTTP {status})"
    if status == 400:
        raise SagaWebValidationError(message, status_code=status)
    raise SagaWebError(message, status_code=status, retryable=_retryable_status(status))


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
