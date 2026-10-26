import datetime

import pytest

from bapp_connectors.core.errors import ProviderError, UnsupportedFeatureError
from bapp_connectors.providers.shop.temu.adapter import BILL_POLL_ATTEMPTS, TemuShopAdapter
from tests.shop.temu.conftest import CREDS, err, ok

START = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
END = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def _adapter(fake, monkeypatch):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    monkeypatch.setattr(adapter, "_sleep", lambda seconds: None)
    return adapter


def test_service_not_supported_propagates(fake, monkeypatch):
    adapter = _adapter(fake, monkeypatch)
    fake.add("POST", "openapi/router", err(200040005, "Service not supported"))
    with pytest.raises(UnsupportedFeatureError):
        adapter.get_financial_transactions(START, END)
    body = fake.last_call().kwargs["json"]
    assert body["type"] == "temu.finance.mall.bill.task.create" and body["fileType"] == "STATEMENT_REPORT"
    assert body["startTime"] == int(START.timestamp() * 1000) and body["endTime"] == int(END.timestamp() * 1000)


def test_polls_task_then_downloads_then_parser_is_unavailable(fake, monkeypatch):
    adapter = _adapter(fake, monkeypatch)
    polls = {"n": 0}

    class R:
        ok = True
        status_code = 200
        content = b"col1,col2\n"
        headers = {}

    def route(method, path, kwargs):
        if method == "GET":
            return R()
        t = kwargs["json"]["type"]
        if t == "temu.finance.mall.bill.task.create":
            return ok({"taskId": "T1", "fileType": "STATEMENT_REPORT", "status": "PROCESSING"})
        polls["n"] += 1
        if polls["n"] < 2:
            return ok({"taskId": "T1", "status": "PROCESSING"})
        return ok({"taskId": "T1", "status": "SUCCESS", "fileUrl": "https://f.example.test/s.csv", "fileName": "s.csv"})

    fake.add(None, "", route)
    with pytest.raises(UnsupportedFeatureError, match="statement report format"):
        adapter.get_financial_transactions(START, END)
    assert polls["n"] == 2 and fake.last_call().method == "GET" and fake.last_call().path.endswith("s.csv")


def test_task_failure_is_a_provider_error(fake, monkeypatch):
    adapter = _adapter(fake, monkeypatch)
    fake.add("POST", "openapi/router", lambda m, p, kw: ok({"taskId": "T1", "status": "PROCESSING"})
             if kw["json"]["type"].endswith("create") else ok({"taskId": "T1", "status": "FAILED", "errorMessage": "nope"}))
    with pytest.raises(ProviderError, match="nope"):
        adapter.get_financial_transactions(START, END)


def test_gives_up_after_max_polls(fake, monkeypatch):
    adapter = _adapter(fake, monkeypatch)
    polls = {"n": 0}

    def route(method, path, kwargs):
        if kwargs["json"]["type"].endswith("create"):
            return ok({"taskId": "T1", "status": "PROCESSING"})
        polls["n"] += 1
        return ok({"taskId": "T1", "status": "PROCESSING"})

    fake.add("POST", "openapi/router", route)
    with pytest.raises(ProviderError, match="not ready"):
        adapter.get_financial_transactions(START, END)
    assert polls["n"] == BILL_POLL_ATTEMPTS


def test_get_invoices_not_implemented(fake, monkeypatch):
    with pytest.raises(NotImplementedError):
        _adapter(fake, monkeypatch).get_invoices()
