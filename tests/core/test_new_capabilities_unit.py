"""FulfillmentCapability, OrderAmountCapability, CustomerDetailsCapability + their DTOs."""

import inspect
from decimal import Decimal

import pytest
from pydantic import ValidationError

from bapp_connectors.core.capabilities import (
    Carrier,
    CustomerDetailsCapability,
    FulfillmentCapability,
    OrderAmountCapability,
    OrderAmounts,
    OrderLineAmounts,
    ShipmentResult,
    ShippingService,
)


def test_capabilities_are_abstract():
    for cap in (FulfillmentCapability, OrderAmountCapability, CustomerDetailsCapability):
        assert inspect.isabstract(cap)


def test_fulfillment_method_names():
    assert {
        "list_carriers",
        "confirm_shipment",
        "list_shipping_services",
        "create_shipment",
        "get_shipment_result",
        "confirm_package_shipped",
    } <= set(FulfillmentCapability.__abstractmethods__)
    assert set(OrderAmountCapability.__abstractmethods__) == {"get_order_amounts"}
    assert set(CustomerDetailsCapability.__abstractmethods__) == {"get_customer_details"}


def test_shipment_result_status_is_constrained():
    ShipmentResult(package_sn="PK-1", status="success")
    with pytest.raises(ValidationError):
        ShipmentResult(package_sn="PK-1", status="done")


def test_order_amounts_defaults():
    line = OrderLineAmounts(item_id="167-1", quantity=Decimal("1"), unit_price_incl_vat=Decimal("59.50"),
                            unit_price_excl_vat=Decimal("50"), vat_rate=Decimal("19"),
                            line_total_incl_vat=Decimal("59.50"), base_price_total=Decimal("45"),
                            discount_seller=Decimal("0"), discount_platform=Decimal("0"),
                            estimated_settlement=Decimal("45"))
    oa = OrderAmounts(order_id="PO-1", currency="RON", lines=[line], shipping_incl_vat=Decimal("0"),
                      shipping_excl_vat=Decimal("0"), tax_total=Decimal("0"), customer_paid_total=Decimal("0"),
                      estimated_revenue=Decimal("0"), estimated_revenue_deduction=Decimal("0"),
                      refunds_total=Decimal("0"), source="amount_query")
    assert oa.extra == {} and oa.lines[0].sku == "" and oa.lines[0].extra == {}
    assert Carrier(carrier_id="1", name="x").extra == {}
    assert ShippingService(service_id="s", name="n").cost is None
    with pytest.raises(ValidationError):
        OrderAmounts(order_id="PO-1", currency="RON", lines=[], shipping_incl_vat=Decimal("0"),
                     shipping_excl_vat=Decimal("0"), tax_total=Decimal("0"), customer_paid_total=Decimal("0"),
                     estimated_revenue=Decimal("0"), estimated_revenue_deduction=Decimal("0"),
                     refunds_total=Decimal("0"), source="guess")
