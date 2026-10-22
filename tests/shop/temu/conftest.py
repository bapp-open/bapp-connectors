"""Shared fixtures for the Temu provider unit tests (no network).

The credentials are the placeholder values from Temu's own signature example, not a real app.
"""

from __future__ import annotations

import pytest

from tests.fake_http import FakeHttpClient

CREDS = {
    "app_key": "f9d5cc9313893a20d5aa85c654e8f503",
    "app_secret": "c7e0a1a63542be4de3cb5488f9fba8149e8fc290",
    "access_token": "tok",
    "region": "eu",
}


def ok(result):
    return {"success": True, "errorCode": 1000000, "errorMsg": "", "requestId": "eu-1", "result": result}


def err(code, msg):
    return {"success": False, "errorCode": code, "errorMsg": msg, "requestId": "eu-2"}


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def client(fake):
    from bapp_connectors.providers.shop.temu.client import TemuApiClient

    return TemuApiClient(CREDS["app_key"], CREDS["app_secret"], CREDS["access_token"], region="eu", http_client=fake)
