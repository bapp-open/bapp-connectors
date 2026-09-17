"""Family-level tests: enum, DTOs, port shapes."""

from abc import ABC
from decimal import Decimal

import pytest
from pydantic import ValidationError

from bapp_connectors.core.dto import HostingAccount, HostingDomain, HostingResource, Mailbox, PanelLink
from bapp_connectors.core.ports import BasePort, HostingPort
from bapp_connectors.core.types import ProviderFamily


def test_hosting_family_enum():
    assert ProviderFamily.HOSTING == "hosting"
    assert ProviderFamily("hosting") is ProviderFamily.HOSTING


def test_dtos_are_frozen_with_defaults():
    acc = HostingAccount(username="u", primary_domain="example.test")
    assert acc.plan == "" and acc.server_hostname == "" and acc.extra == {}
    with pytest.raises(ValidationError):
        acc.plan = "x"  # frozen

    res = HostingResource(key="disk_usage")
    assert res.used is None and res.limit is None and res.unit == "" and res.percent is None

    dom = HostingDomain(domain="example.test", kind="main")
    assert dom.document_root == "" and dom.ssl_expires_at is None and dom.ssl_auto is False

    box = Mailbox(email="a@example.test", login="a@example.test", domain="example.test")
    assert box.disk_used is None and box.disk_quota is None
    assert box.suspended_login is False and box.suspended_incoming is False

    link = PanelLink(url="https://cpanel.example.net:2083/", kind="panel", single_sign_on=False)
    assert link.expires_at is None


def test_resource_accepts_decimal_amounts():
    res = HostingResource(key="disk_usage", used=Decimal("1305116672"), limit=Decimal("128849018880"), unit="bytes")
    assert res.used == Decimal("1305116672")


def test_port_is_abstract():
    assert issubclass(HostingPort, BasePort)
    assert issubclass(HostingPort, ABC)
    with pytest.raises(TypeError):
        HostingPort()  # type: ignore[abstract]
    assert {
        "get_account",
        "get_usage",
        "list_domains",
        "validate_credentials",
        "test_connection",
    } <= HostingPort.__abstractmethods__
