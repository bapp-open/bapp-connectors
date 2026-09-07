from datetime import datetime
from decimal import Decimal

from bapp_connectors.core.dto import CustomerPricing, CustomerProductPercent, ShopRules


def test_shop_rules_defaults_the_new_rolling_ceiling_to_zero():
    assert ShopRules().max_rolling_order_percent == Decimal("0")


def test_customer_pricing_carries_percentages_and_nothing_else():
    record = CustomerPricing(
        customer_key="12345678",
        order_value_percent=Decimal("3.00"),
        product_percents=[CustomerProductPercent(sku="P-100", discount_percent=Decimal("4.00"))],
        computed_at=datetime(2026, 9, 7, 3, 0, 0),
    )
    assert record.product_percents[0].sku == "P-100"
    keys = set(record.model_dump())
    assert {"customer_key", "order_value_percent", "product_percents", "computed_at", "extra"} <= keys
    assert not keys & {"name", "company_name", "address", "email", "phone", "trading_history"}


def test_customer_pricing_defaults_to_a_zero_level_with_no_products():
    record = CustomerPricing(customer_key="12345678")
    assert record.order_value_percent == Decimal("0")
    assert record.product_percents == []
