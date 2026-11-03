"""
SAGA Web adapter — implements AccountingPort.

Import pushes one XML file (invoices, receipts, payments, nomenclatures); the reads return the
stock situation, account balances, the trial balance and articles. Every call goes through
``SagaWebApiClient``, which saves the rotated key through ``on_credentials_update``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from bapp_connectors.core.dto import (
    Article,
    ConnectionTestResult,
    ImportResult,
    ImportStatus,
    StockLine,
    TrialBalanceLine,
)
from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import AccountingPort
from bapp_connectors.providers.accounting.saga_web.client import SagaWebApiClient
from bapp_connectors.providers.accounting.saga_web.errors import (
    SagaWebAuthError,
    SagaWebError,
    SagaWebValidationError,
)
from bapp_connectors.providers.accounting.saga_web.manifest import ALLOWED_HOST, DEFAULT_BASE_URL, manifest
from bapp_connectors.providers.accounting.saga_web.mappers import (
    parse_article,
    parse_envelope,
    parse_report,
    parse_stock_report,
    parse_trial_balance,
    saga_date,
    to_decimal,
)

if TYPE_CHECKING:
    from collections.abc import Callable

AUTH_REFUSED_MESSAGE = (
    "SAGA Web a refuzat cheia de acces (HTTP 401/403). Generează o cheie nouă din Utilizatori → Integrare API."
)
COD_FISCAL_MESSAGE = "Codul fiscal trebuie să conțină doar cifre"
_INVALID_ARTICLE_HINT = "cod de articol"


def base_url_error(base_url: str) -> str:
    """Why ``base_url`` may not carry the key, or "" when it may.

    The key only goes over https to sagasoft.ro or a subdomain of it.
    """
    try:
        parts = urlsplit(base_url or "")
        host = (parts.hostname or "").lower()
    except ValueError:
        return "URL API invalid"
    if parts.scheme != "https":
        return "URL API trebuie să fie https"
    if host != ALLOWED_HOST and not host.endswith("." + ALLOWED_HOST):
        return f"URL API trebuie să fie pe {ALLOWED_HOST}"
    return ""


def clean_cod_fiscal(value: str) -> str:
    """The CUI as SAGA wants it: no spaces, no ``RO`` prefix (``" RO 6716875"`` → ``"6716875"``)."""
    cleaned = "".join((value or "").split())
    if cleaned[:2].upper() == "RO":
        cleaned = cleaned[2:]
    return cleaned


def _cod_fiscal_ok(value: str) -> bool:
    return value.isascii() and value.isdigit()


def _parsed(parser: Callable[[str], Any], text: str, *, is_envelope: bool = False) -> Any:
    """Run a mapper on a 2xx body; bad XML or a malformed number becomes a ``SagaWebError``."""
    try:
        return parser(text)
    except ValueError as exc:
        raise SagaWebError(
            f"Răspuns SAGA Web invalid: {exc}", status_code=200, retryable=False, is_envelope=is_envelope
        ) from None


class SagaWebAdapter(AccountingPort):
    """SAGA Web adapter (AccountingPort)."""

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        on_credentials_update: Callable[[dict], None] | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}
        base_url = credentials.get("base_url") or DEFAULT_BASE_URL
        # checked here, raised on use: building the adapter (listing, schema) must not break
        self._base_url_error = base_url_error(base_url)

        if http_client is None:
            http_client = ResilientHttpClient(base_url=base_url, provider_name="saga_web")

        self._cod_fiscal = clean_cod_fiscal(credentials.get("cod_fiscal") or "")
        self.client = SagaWebApiClient(
            http_client=http_client,
            token=(credentials.get("token") or "").strip(),
            cod_fiscal=self._cod_fiscal,
            base_url=base_url,
            on_credentials_update=on_credentials_update,
        )

    def __repr__(self) -> str:
        return f"SagaWebAdapter(client={self.client!r})"

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return (
            not self.manifest.auth.validate_credentials(self.credentials)
            and self._base_url_error == ""
            and _cod_fiscal_ok(self._cod_fiscal)
            and bool(self.client.token)
        )

    def test_connection(self) -> ConnectionTestResult:
        if not _cod_fiscal_ok(self._cod_fiscal):
            return ConnectionTestResult(success=False, message=COD_FISCAL_MESSAGE)
        try:
            balance = self.get_account_balance("5311", "D", date.today())
        except ConfigurationError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        except SagaWebAuthError:
            return ConnectionTestResult(success=False, message=AUTH_REFUSED_MESSAGE)
        except SagaWebError as exc:
            if exc.is_envelope and exc.status_code in (200, 400):
                # SAGA's own envelope past the key check: the key works, the query did not
                return ConnectionTestResult(success=True, message="Conexiune reușită", details={"warning": str(exc)})
            if exc.status_code is not None:
                # an answer SAGA did not vouch for: an HTML page, a 404 off a wrong URL, a 5xx
                return ConnectionTestResult(
                    success=False, message=f"SAGA Web a răspuns cu HTTP {exc.status_code} — verifică URL-ul API"
                )
            # no HTTP answer (timeout, network): nothing says the key works
            return ConnectionTestResult(success=False, message=str(exc))
        except Exception as exc:
            return ConnectionTestResult(success=False, message=f"Eroare neașteptată ({type(exc).__name__})")
        return ConnectionTestResult(
            success=True, message="Conexiune reușită", details={"balance_5311_debit": str(balance)}
        )

    # ── AccountingPort ──

    def _ensure_base_url(self) -> None:
        if self._base_url_error:
            raise ConfigurationError(self._base_url_error)

    def import_file(self, filename: str, content: bytes, auto_import: bool = True) -> ImportResult:
        self._ensure_base_url()
        response = self.client.import_file(filename, content, auto_import)
        status = response.status_code
        text = response.text or ""
        if status == 200:
            success, message, _ = parse_envelope(text)
            return ImportResult(
                status=ImportStatus.OK if success else ImportStatus.FAILED, http_status=status, message=message
            )
        if status in (207, 422):
            return ImportResult(
                status=ImportStatus.PARTIAL if status == 207 else ImportStatus.FAILED,
                http_status=status,
                report=text,
                problems=parse_report(text),
            )
        if status == 400:
            _, message, _ = parse_envelope(text)
            return ImportResult(status=ImportStatus.FAILED, http_status=status, message=message)
        _, message, _ = parse_envelope(text)
        # never replayed: SAGA may have taken part of the file before failing
        raise SagaWebError(message or f"SAGA Web a răspuns cu HTTP {status}", status_code=status, retryable=False)

    def _get_value(self, path: str, params: dict) -> Decimal:
        self._ensure_base_url()
        success, message, data = self.client.get_json(path, params)
        if not success:
            raise SagaWebError(
                message or "SAGA Web nu a returnat valoarea cerută", status_code=200, retryable=False, is_envelope=True
            )
        return _parsed(to_decimal, data, is_envelope=True)

    def _get_xml(self, path: str, params: dict) -> str:
        self._ensure_base_url()
        return self.client.get_xml(path, params)

    def get_article_stock(self, article_code: str, warehouse: str = "", day: date | None = None) -> Decimal:
        params = {"codArticol": article_code}
        if warehouse:
            params["gestiune"] = warehouse
        if day is not None:
            params["data"] = saga_date(day)
        return self._get_value("Situatii/GetStocArticol", params)

    def get_stock_report(self, start: date, end: date) -> list[StockLine]:
        xml = self._get_xml("Situatii/GetSituatieStocuri", {"dataStart": saga_date(start), "dataEnd": saga_date(end)})
        return _parsed(parse_stock_report, xml)

    def get_account_balance(self, account: str, side: str, day: date | None = None) -> Decimal:
        params = {"cont": account, "tip": side, "data": saga_date(day or date.today())}
        return self._get_value("Situatii/GetSoldCont", params)

    def get_trial_balance(self, start: date, end: date, analytic: bool = False) -> list[TrialBalanceLine]:
        params = {"dataStart": saga_date(start), "dataEnd": saga_date(end), "tipBalanta": "1" if analytic else "0"}
        return _parsed(parse_trial_balance, self._get_xml("Situatii/GetBalanta", params))

    def get_article(self, article_code: str) -> Article | None:
        try:
            xml = self._get_xml("Situatii/GetArticol", {"codArticol": article_code})
        except SagaWebValidationError as exc:
            # SAGA answers 400 "Nu ati trimis un cod de articol valid" for an unknown code
            if _INVALID_ARTICLE_HINT in str(exc).lower():
                return None
            raise
        return _parsed(parse_article, xml)
