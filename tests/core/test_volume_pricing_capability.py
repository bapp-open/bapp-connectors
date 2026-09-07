import inspect

import pytest

from bapp_connectors.core.capabilities import VolumePricingCapability


def test_an_adapter_missing_push_customer_pricing_cannot_be_instantiated():
    class Half(VolumePricingCapability):
        def push_shop_rules(self, rules):
            pass

    with pytest.raises(TypeError, match="push_customer_pricing"):
        Half()


def test_full_defaults_to_true_and_is_keyword_only():
    signature = inspect.signature(VolumePricingCapability.push_customer_pricing)
    full = signature.parameters["full"]
    assert full.kind is inspect.Parameter.KEYWORD_ONLY
    assert full.default is True
