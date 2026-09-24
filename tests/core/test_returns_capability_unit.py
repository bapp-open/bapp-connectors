from datetime import UTC, datetime
from decimal import Decimal

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.core.dto import ReturnKind, ShopReturn, ShopReturnLine, ShopReturnRefund


class _Impl(ReturnsCapability):
    def get_returns(self, since, until):
        return [ShopReturn(external_id="1", lines=[ShopReturnLine(sku="A", quantity=Decimal(2))])]


def test_defaults_and_kind():
    r = ShopReturn(external_id="1")
    assert r.kind == ReturnKind.RETURN and r.lines == [] and r.refund is None and r.awb == ""


def test_refund_and_line():
    ref = ShopReturnRefund(amount=Decimal("22.89"), currency="RON", at=datetime(2026, 9, 22, tzinfo=UTC))
    assert ref.estimated is False and ref.amount == Decimal("22.89")
    assert ShopReturnLine().quantity == Decimal(1)


def test_capability_default_awb_resolution_is_empty():
    impl = _Impl()
    assert impl.resolve_return_awb("123") == ""
    assert impl.get_returns(datetime.now(UTC), datetime.now(UTC))[0].lines[0].sku == "A"
