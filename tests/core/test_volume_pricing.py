"""ShopRules DTO and VolumePricingCapability."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError


class TestShopRulesDTO:

    def test_order_value_tier_holds_decimals(self):
        from bapp_connectors.core.dto import OrderValueTier

        tier = OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00"))

        assert tier.min_total == Decimal("5000.00")
        assert tier.discount_percent == Decimal("3.00")

    def test_shop_rules_defaults(self):
        from bapp_connectors.core.dto import ShopRules

        rules = ShopRules()

        assert rules.order_value_tiers == []
        assert rules.min_order_total is None
        assert rules.currency == ""
        assert rules.extra == {}
        assert rules.provider_meta is None

    def test_shop_rules_is_frozen(self):
        from bapp_connectors.core.dto import ShopRules

        rules = ShopRules(currency="RON")

        with pytest.raises(ValidationError):
            rules.currency = "EUR"

    def test_shop_rules_full(self):
        from bapp_connectors.core.dto import OrderValueTier, ShopRules

        rules = ShopRules(
            order_value_tiers=[OrderValueTier(min_total=Decimal("1000"), discount_percent=Decimal("2"))],
            min_order_total=Decimal("500"),
            currency="RON",
            extra={"connection_id": 123},
        )

        assert rules.order_value_tiers[0].min_total == Decimal("1000")
        assert rules.min_order_total == Decimal("500")
        assert rules.extra["connection_id"] == 123


class TestVolumePricingCapability:

    def test_is_abstract(self):
        from bapp_connectors.core.capabilities import VolumePricingCapability

        with pytest.raises(TypeError):
            VolumePricingCapability()

    def test_concrete_adapter_receives_rules(self):
        from bapp_connectors.core.capabilities import VolumePricingCapability
        from bapp_connectors.core.dto import ShopRules

        class _Adapter(VolumePricingCapability):
            def __init__(self):
                self.pushed: list[ShopRules] = []

            def push_shop_rules(self, rules: ShopRules) -> None:
                self.pushed.append(rules)

            def push_customer_pricing(self, records, *, full: bool = True) -> None:
                raise NotImplementedError

        adapter = _Adapter()
        rules = ShopRules(currency="RON", min_order_total=Decimal("1000"))
        adapter.push_shop_rules(rules)

        assert adapter.pushed == [rules]
        assert isinstance(adapter, VolumePricingCapability)
