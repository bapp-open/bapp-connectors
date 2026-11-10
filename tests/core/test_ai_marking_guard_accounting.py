"""Guard on the ``@ai_method`` markers of the accounting provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
accounting credentials. Every one of them was read down to its HTTP request; the lists below are
that review.

SAGA Web: the client only had ``get_json(path, params)`` / ``get_xml(path, params)``, which take
any path; they stay unmarked. The agent gets fixed ``Situatii/*`` GETs instead (stock, balances,
trial balance, one article). ``import_file`` posts into the books and is never offered. Like any
SAGA call, a read may rotate the key; the client saves it through ``on_credentials_update``.
"""

from __future__ import annotations

import inspect
import json
from datetime import date

import pytest

from bapp_connectors.core.ai import ai_methods
from tests.core import ai_guard
from tests.fake_http import FakeHttpClient

FAMILY = "accounting"
ACCOUNTING_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "saga_web": {
        "get_account_balance",  # GET Situatii/GetSoldCont
        "get_article",  # GET Situatii/GetArticol
        "get_article_stock",  # GET Situatii/GetStocArticol
        "get_stock_report",  # GET Situatii/GetSituatieStocuri
        "get_trial_balance",  # GET Situatii/GetBalanta
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = set()

UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("saga_web", "get_json"): "GETs any path the caller gives",
    ("saga_web", "get_xml"): "GETs any path the caller gives",
    ("saga_web", "import_file"): "posts documents into the books",
}

NOT_MARKED: dict[str, str] = {}


def test_every_accounting_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in ACCOUNTING_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_accounting_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", _CHECKED)
def test_every_public_method_is_marked_or_left_out_on_purpose(provider):
    """A new public client method fails here until it is marked or listed as unmarked."""
    cls = ai_guard.client_cls(FAMILY, provider)
    marked = set(ai_methods(cls))
    public = {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, (staticmethod, classmethod))
    }
    assert public - marked == {m for p, m in UNMARKED_ON_PURPOSE if p == provider}


@pytest.mark.parametrize("provider", _CHECKED)
def test_no_read_takes_a_path_or_host(provider):
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"path", "url", "base_url", "host", "endpoint", "params"}, name


# ── SAGA Web ──

BASE = "https://web2.sagasoft.ro/sagac/api/v20260225/"


class _Response:
    def __init__(self, status_code=200, body=None, text=None, headers=None):
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(body)
        self.headers = headers or {}


def _envelope(data):
    return _Response(200, {"success": True, "message": "", "data": data})


def _saga(http, callback=None):
    from bapp_connectors.providers.accounting.saga_web.client import SagaWebApiClient

    return SagaWebApiClient(http, token="K1", cod_fiscal="6716875", base_url=BASE, on_credentials_update=callback)


def test_saga_reads_get_fixed_paths_once():
    http = FakeHttpClient()
    http.add("GET", "GetStocArticol", _envelope("7"))
    http.add("GET", "GetSoldCont", _envelope("12,50"))
    http.add("GET", "GetSituatieStocuri", _Response(200, text="<Situatie></Situatie>"))
    http.add("GET", "GetBalanta", _Response(200, text="<Balanta></Balanta>"))
    http.add("GET", "GetArticol", _Response(200, text="<Articol><Denumire>Pix</Denumire></Articol>"))
    client = _saga(http)

    out = client.get_article_stock("A1", warehouse="G1", day=date(2026, 11, 1))
    assert str(out["stock"]) == "7"
    out = client.get_account_balance("5311", "D", day=date(2026, 11, 1))
    assert str(out["balance"]) == "12.50"
    assert client.get_stock_report(date(2026, 1, 1), date(2026, 1, 31)) == []
    assert client.get_trial_balance(date(2026, 1, 1), date(2026, 1, 31), analytic=True) == []
    assert client.get_article("A1").name == "Pix"

    assert [(c.method, c.path.removeprefix(BASE)) for c in http.calls] == [
        ("GET", "Situatii/GetStocArticol"),
        ("GET", "Situatii/GetSoldCont"),
        ("GET", "Situatii/GetSituatieStocuri"),
        ("GET", "Situatii/GetBalanta"),
        ("GET", "Situatii/GetArticol"),
    ]
    assert http.calls[0].kwargs["params"] == {"codArticol": "A1", "gestiune": "G1", "data": "01.11.2026"}
    assert http.calls[1].kwargs["params"] == {"cont": "5311", "tip": "D", "data": "01.11.2026"}
    assert http.calls[3].kwargs["params"]["tipBalanta"] == "1"


def test_saga_unknown_article_is_none():
    http = FakeHttpClient()
    http.add(
        "GET", "GetArticol", _Response(400, {"success": False, "message": "Nu ati trimis un cod de articol valid"})
    )
    assert _saga(http).get_article("NOPE") is None


def test_saga_read_saves_a_rotated_key():
    saved = []
    http = FakeHttpClient()
    resp = _envelope("1")
    resp.headers = {"X-Saga-Refresh-Token": "K2"}
    http.add("GET", "GetSoldCont", resp)
    client = _saga(http, saved.append)
    client.get_account_balance("5311", "C")
    assert saved == [{"token": "K2"}]
    assert client.token == "K2"


def test_saga_no_ai_client_when_the_url_may_not_carry_the_key():
    from bapp_connectors.core.registry import registry

    good = ai_guard.adapter(FAMILY, "saga_web")
    assert good.get_ai_client() is good.client
    with ai_guard.no_network():
        bad = registry.create_adapter(
            FAMILY, "saga_web", credentials={"base_url": "https://evil.example.com/", "cod_fiscal": "1", "token": "x"}
        )
    assert bad.get_ai_client() is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com\\.sagasoft.ro/api",
        "https://evil.com\\@web.sagasoft.ro/api",
        "https://user@web.sagasoft.ro/api",
        "https://evil.com%2F.sagasoft.ro/api",
        "https://web.sagasoft.ro%40evil.com/api",
        "https://evil.com .sagasoft.ro/api",
    ],
)
def test_saga_base_url_host_checked_as_requests_sends_it(url):
    import requests

    from bapp_connectors.providers.accounting.saga_web.adapter import base_url_error

    assert base_url_error(url) != ""
    if "\\" in url:  # what made the check necessary: urllib3 sends this one to evil.com
        assert requests.Request("GET", url).prepare().url.startswith("https://evil.com/")


@pytest.mark.parametrize("url", ["https://web.sagasoft.ro/api/", "https://web2.sagasoft.ro:443/sagac/api/v1/"])
def test_saga_base_url_good_hosts_still_accepted(url):
    from bapp_connectors.providers.accounting.saga_web.adapter import base_url_error

    assert base_url_error(url) == ""
