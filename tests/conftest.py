"""Shared test fixtures."""

from urllib.parse import urlsplit

import pytest
from requests.adapters import HTTPAdapter

_REAL_SEND = HTTPAdapter.send


def _is_bapp_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "bapp.ro" or host.endswith(".bapp.ro")


def _guarded_send(self, request, *args, **kwargs):
    # A test that forgets to inject an http_client must not reach the production ERP: on
    # 2026-10-20 a mocked BAPP adapter POSTed to panel.bapp.ro (Sentry aio-backend 23158).
    # `responses` patches HTTPAdapter.send itself, so mocked calls never get here.
    if _is_bapp_host(request.url):
        raise RuntimeError(f"Test tried a real HTTP request to {request.url}; mock the HTTP client.")
    return _REAL_SEND(self, request, *args, **kwargs)


@pytest.fixture(autouse=True)
def _no_real_bapp_requests(monkeypatch):
    monkeypatch.setattr(HTTPAdapter, "send", _guarded_send)

