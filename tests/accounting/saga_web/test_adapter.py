"""SagaWebAdapter: registration, credentials, test_connection, import statuses and reads."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import requests

from bapp_connectors.core.dto import ImportStatus
from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.registry import registry
from bapp_connectors.core.types import ProviderFamily
from bapp_connectors.providers.accounting.saga_web import SagaWebAdapter, manifest
from bapp_connectors.providers.accounting.saga_web.adapter import base_url_error
from bapp_connectors.providers.accounting.saga_web.errors import SagaWebError
from bapp_connectors.providers.accounting.saga_web.mappers import saga_date
from tests.accounting.contract import AccountingContractTests
from tests.fake_http import FakeHttpClient

FIX = Path(__file__).parent / "fixtures"
BASE = "https://web2.sagasoft.ro/sagac/api/v20260225/"
KEY = "SECRET-KEY-123"


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body)
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def envelope(data="", success=True, message="", status=200, headers=None):
    return FakeResponse(status, {"success": success, "message": message, "data": data}, headers=headers)


def creds(**extra):
    return {"token": KEY, "cod_fiscal": "6716875", "base_url": BASE, **extra}


def make_adapter(http=None, callback=None, **extra):
    http = http or FakeHttpClient()
    return SagaWebAdapter(credentials=creds(**extra), http_client=http, on_credentials_update=callback), http


# ── registration / manifest ──


def test_registered_in_registry():
    assert registry.get_adapter_class("accounting", "saga_web") is SagaWebAdapter
    assert manifest.family == ProviderFamily.ACCOUNTING
    assert manifest.auth.rotating_credentials is True
    assert [f.name for f in manifest.auth.required_fields] == ["base_url", "cod_fiscal", "token"]
    assert next(f for f in manifest.auth.required_fields if f.name == "token").sensitive is True


def test_create_adapter_passes_callback_kwarg():
    updates = []
    adapter = registry.create_adapter("accounting", "saga_web", creds(), on_credentials_update=updates.append)
    assert adapter.client.on_credentials_update == updates.append
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", envelope("1", headers={"X-Saga-Refresh-Token": "K2"}))
    adapter.client.http = http
    adapter.get_account_balance("5311", "D", date(2026, 1, 1))
    assert updates == [{"token": "K2"}]


def test_key_not_in_repr():
    adapter, _ = make_adapter()
    assert KEY not in repr(adapter)
    assert KEY not in repr(adapter.client)


# ── credentials / base_url ──


def test_validate_credentials_rejects_foreign_host():
    assert make_adapter(base_url="https://evil.test/api/")[0].validate_credentials() is False
    assert make_adapter(base_url="http://web.sagasoft.ro/api/")[0].validate_credentials() is False
    assert make_adapter(base_url="https://sagasoft.ro.evil.test/")[0].validate_credentials() is False
    assert make_adapter(base_url="https://web2.sagasoft.ro/sagac/api/v20260225/")[0].validate_credentials() is True
    assert make_adapter(base_url="")[0].validate_credentials() is False  # required credential
    assert make_adapter(token="")[0].validate_credentials() is False


def test_base_url_error_messages():
    assert base_url_error("https://web.sagasoft.ro/api/") == ""
    assert base_url_error("https://sagasoft.ro/api/") == ""
    assert base_url_error("http://web.sagasoft.ro/api/") == "URL API trebuie să fie https"
    assert base_url_error("https://evil.test/") == "URL API trebuie să fie pe sagasoft.ro"
    assert base_url_error("https://[bad") == "URL API invalid"


def test_bad_base_url_never_calls_out():
    adapter, http = make_adapter(base_url="https://evil.test/api/")
    result = adapter.test_connection()
    assert result.success is False
    assert result.message == "URL API trebuie să fie pe sagasoft.ro"
    with pytest.raises(ConfigurationError, match=r"sagasoft\.ro"):
        adapter.get_stock_report(date(2026, 1, 1), date(2026, 1, 31))
    assert http.calls == []


# ── test_connection ──


def test_test_connection_ok_uses_sold_cont():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetSoldCont", envelope("3142.9"))
    adapter, _ = make_adapter(http)
    result = adapter.test_connection()
    assert result.success is True
    assert result.details["balance_5311_debit"] == "3142.9"
    assert http.last_call().kwargs["params"] == {"cont": "5311", "tip": "D", "data": saga_date(date.today())}


def test_test_connection_auth_error():
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", FakeResponse(401, text=""))
    result = make_adapter(http)[0].test_connection()
    assert result.success is False
    assert "Integrare API" in result.message
    assert KEY not in result.message


def test_test_connection_other_error_is_authenticated_warning():
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", envelope(success=False, message="Contul nu exista", status=400))
    result = make_adapter(http)[0].test_connection()
    assert result.success is True
    assert result.details == {"warning": "Contul nu exista"}


def test_test_connection_200_success_false_is_authenticated_warning():
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", envelope(success=False, message="Cont inexistent"))
    result = make_adapter(http)[0].test_connection()
    assert result.success is True
    assert result.details == {"warning": "Cont inexistent"}


def test_test_connection_400_json_cont_inexistent_is_warning():
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", FakeResponse(400, {"success": False, "error": "cont inexistent"}))
    result = make_adapter(http)[0].test_connection()
    assert result.success is True
    assert result.details == {"warning": "cont inexistent"}


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (200, "<html><body>SAGA Web</body></html>"),
        (404, "<html><body>404 Not Found</body></html>"),
        (502, "<html><body>502 Bad Gateway</body></html>"),
        (404, '{"success": false, "message": "nu exista"}'),
        (500, '{"success": false, "message": "Eroare interna"}'),
    ],
)
def test_test_connection_answer_saga_did_not_vouch_for_fails(status, text):
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", FakeResponse(status, text=text))
    result = make_adapter(http)[0].test_connection()
    assert result.success is False
    assert result.message == f"SAGA Web a răspuns cu HTTP {status} — verifică URL-ul API"


@pytest.mark.parametrize("status", [401, 403])
def test_test_connection_401_403_says_new_key(status):
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", FakeResponse(status, text="<html>Forbidden</html>"))
    result = make_adapter(http)[0].test_connection()
    assert result.success is False
    assert "generează o cheie nouă" in result.message.lower()


def test_test_connection_transport_error_fails():
    def boom(method, path, kwargs):
        raise requests.ConnectionError("refused")

    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", boom)
    result = make_adapter(http)[0].test_connection()
    assert result.success is False
    assert "ConnectionError" in result.message


def test_test_connection_never_raises():
    def boom(method, path, kwargs):
        raise RuntimeError("unexpected")

    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", boom)
    result = make_adapter(http)[0].test_connection()
    assert result.success is False


# ── import ──


def test_import_200_ok():
    http = FakeHttpClient()
    http.add("POST", "Import", envelope(message="Import realizat cu succes."))
    result = make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>")
    assert result.status == ImportStatus.OK
    assert result.http_status == 200
    assert result.message == "Import realizat cu succes."
    assert http.last_call().kwargs["data"] == {"importAutomat": "true"}


def test_import_auto_import_false_passed_on():
    http = FakeHttpClient()
    http.add("POST", "Import", envelope(message="ok"))
    make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>", auto_import=False)
    assert http.last_call().kwargs["data"] == {"importAutomat": "false"}


def test_import_200_success_false_is_failed():
    http = FakeHttpClient()
    http.add("POST", "Import", envelope(success=False, message="Fisier XML invalid."))
    result = make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>")
    assert result.status == ImportStatus.FAILED
    assert result.message == "Fisier XML invalid."


def test_import_207_partial_with_problems():
    text = (FIX / "raport_207.txt").read_text()
    http = FakeHttpClient()
    http.add("POST", "Import", FakeResponse(207, text=text))
    result = make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>")
    assert result.status == ImportStatus.PARTIAL
    assert result.http_status == 207
    assert result.report == text
    assert result.problems[0].document_number == "A100"
    assert len(result.problems) == 2


def test_import_422_failed():
    text = (FIX / "raport_207.txt").read_text()
    http = FakeHttpClient()
    http.add("POST", "Import", FakeResponse(422, text=text))
    result = make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>")
    assert result.status == ImportStatus.FAILED
    assert result.http_status == 422
    assert result.report == text
    assert result.problems[1].document_number == "A1002"


def test_import_400_failed_with_envelope_message():
    http = FakeHttpClient()
    http.add("POST", "Import", envelope(success=False, message="Lipseste fisierul", status=400))
    result = make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>")
    assert result.status == ImportStatus.FAILED
    assert result.http_status == 400
    assert result.message == "Lipseste fisierul"


def test_import_other_status_raises():
    http = FakeHttpClient()
    http.add("POST", "Import", FakeResponse(500, text="oops"))
    with pytest.raises(SagaWebError) as exc:
        make_adapter(http)[0].import_file("F_1.xml", b"<Facturi/>")
    assert exc.value.status_code == 500


# ── reads ──


def test_reads_map_params_and_parse():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetSituatieStocuri", FakeResponse(200, text=(FIX / "situatie.xml").read_text()))
    http.add("GET", "Situatii/GetBalanta", FakeResponse(200, text=(FIX / "balanta.xml").read_text()))
    http.add("GET", "Situatii/GetStocArticol", envelope("174852"))
    http.add(
        "GET",
        "Situatii/GetArticol",
        envelope(success=False, message="Nu ati trimis un cod de articol valid", status=400),
    )
    adapter, _ = make_adapter(http)

    lines = adapter.get_stock_report(date(2026, 1, 1), date(2026, 1, 31))
    assert http.last_call().kwargs["params"] == {"dataStart": "01.01.2026", "dataEnd": "31.01.2026"}
    assert lines[0].article_code == "00000001" and lines[0].qty_final == Decimal("136")

    balance = adapter.get_trial_balance(date(2026, 1, 1), date(2026, 1, 31), analytic=True)
    assert http.last_call().kwargs["params"] == {"dataStart": "01.01.2026", "dataEnd": "31.01.2026", "tipBalanta": "1"}
    assert balance[0].account == "371"
    adapter.get_trial_balance(date(2026, 1, 1), date(2026, 1, 31))
    assert http.last_call().kwargs["params"]["tipBalanta"] == "0"

    assert adapter.get_article_stock("0001", "0001", date(2026, 2, 3)) == Decimal("174852")
    assert http.last_call().kwargs["params"] == {"codArticol": "0001", "gestiune": "0001", "data": "03.02.2026"}
    adapter.get_article_stock("0001")
    assert http.last_call().kwargs["params"] == {"codArticol": "0001"}

    assert adapter.get_article("bad") is None
    assert http.last_call().kwargs["params"] == {"codArticol": "bad"}


def test_get_article_parses_xml():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetArticol", FakeResponse(200, text=(FIX / "articol.xml").read_text()))
    article = make_adapter(http)[0].get_article("00000001")
    assert article.name == "ARTICOL"


def test_get_article_other_validation_error_raises():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetArticol", envelope(success=False, message="Alta eroare", status=400))
    with pytest.raises(SagaWebError, match="Alta eroare"):
        make_adapter(http)[0].get_article("x")


def test_account_balance_params():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetSoldCont", envelope("12,5"))
    assert make_adapter(http)[0].get_account_balance("5121", "C", date(2026, 3, 1)) == Decimal("12.5")
    assert http.last_call().kwargs["params"] == {"cont": "5121", "tip": "C", "data": "01.03.2026"}


def test_json_success_false_raises():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetStocArticol", envelope(success=False, message="Articol inexistent"))
    with pytest.raises(SagaWebError, match="Articol inexistent"):
        make_adapter(http)[0].get_article_stock("0001")


def test_invalid_xml_and_number_become_saga_web_error():
    http = FakeHttpClient()
    http.add("GET", "Situatii/GetSituatieStocuri", FakeResponse(200, text="<Situatie"))
    http.add("GET", "Situatii/GetSoldCont", envelope("1.234,56"))
    adapter, _ = make_adapter(http)
    with pytest.raises(SagaWebError, match="Răspuns SAGA Web invalid"):
        adapter.get_stock_report(date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(SagaWebError, match="Răspuns SAGA Web invalid"):
        adapter.get_account_balance("5311", "D")


# ── contract ──


class TestSagaWebContract(AccountingContractTests):
    @pytest.fixture
    def accounting_adapter(self):
        http = FakeHttpClient()
        http.add("GET", "Situatii/GetSoldCont", envelope("3142.9"))
        http.add("GET", "Situatii/GetSituatieStocuri", FakeResponse(200, text=(FIX / "situatie.xml").read_text()))
        http.add("POST", "Import", envelope(message="Import realizat cu succes."))
        return make_adapter(http)[0]


# ── pasted credentials ──


def test_cod_fiscal_and_token_are_cleaned():
    http = FakeHttpClient()
    http.add("GET", "GetSoldCont", envelope("1"))
    adapter, _ = make_adapter(http, cod_fiscal=" RO6716875", token=KEY + "\n")
    assert adapter.validate_credentials() is True
    adapter.test_connection()
    headers = http.last_call().kwargs["headers"]
    assert headers["X-Saga-Cod-Fiscal"] == "6716875"
    assert headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("value", ["ro 6716 875", "RO6716875 ", "6716875"])
def test_clean_cod_fiscal(value):
    from bapp_connectors.providers.accounting.saga_web.adapter import clean_cod_fiscal

    assert clean_cod_fiscal(value) == "6716875"


@pytest.mark.parametrize("value", ["RO67-16875", "J40/1/2020", "６７１６８７５", "RO"])
def test_non_digit_cod_fiscal_is_refused(value):
    http = FakeHttpClient()
    adapter, _ = make_adapter(http, cod_fiscal=value)
    assert adapter.validate_credentials() is False
    result = adapter.test_connection()
    assert result.success is False
    assert result.message == "Codul fiscal trebuie să conțină doar cifre"
    assert http.calls == []
