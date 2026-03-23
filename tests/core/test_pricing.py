"""Tests for price/VAT conversion utilities."""

from decimal import Decimal

from bapp_connectors.core.pricing import to_gross, to_net


def test_to_gross_19_percent():
    assert to_gross(Decimal("100.00"), 0.19) == Decimal("119.00")


def test_to_net_19_percent():
    assert to_net(Decimal("119.00"), 0.19) == Decimal("100.00")


def test_roundtrip_19_percent():
    net = Decimal("29.99")
    gross = to_gross(net, 0.19)
    back = to_net(gross, 0.19)
    assert back == net


def test_to_gross_zero_vat():
    assert to_gross(Decimal("50.00"), 0.0) == Decimal("50.00")


def test_to_net_zero_vat():
    assert to_net(Decimal("50.00"), 0.0) == Decimal("50.00")


def test_to_gross_decimal_rate():
    assert to_gross(Decimal("100.00"), Decimal("0.19")) == Decimal("119.00")


def test_rounding():
    # 33.33 * 1.19 = 39.6627 → 39.66
    assert to_gross(Decimal("33.33"), 0.19) == Decimal("39.66")


def test_to_net_rounding():
    # 39.66 / 1.19 = 33.3277... → 33.33
    assert to_net(Decimal("39.66"), 0.19) == Decimal("33.33")
