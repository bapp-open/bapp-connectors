"""Fixture parity: the JSON files under the package are the cross-repo contract."""
import json
from decimal import ROUND_HALF_UP, Decimal
from importlib.resources import files

import pytest

from bapp_connectors.core.pricing import to_gross

FIXTURES = files("bapp_connectors.providers.shop.bapp_store") / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fixture_files_exist_and_parse():
    batch = _load("products_batch.json")
    rules = _load("rules.json")
    orders = _load("orders_export.json")
    cases = _load("pricing_cases.json")
    assert [c["id"] for c in batch["request"]["categories"]] == ["159", "160"]
    assert [p["code"] for p in batch["request"]["products"]] == ["CIO-500", "BAL-60", "BUR-10"]
    assert rules["request"]["rules"]["min_order_total"] == "1000.00"
    assert orders["items"][0]["number"] == "ORD-000123"
    assert [c["name"] for c in cases["cases"]] == [
        "worked_example",
        "below_minimum",
        "category_ancestor_rule",
        "non_discountable_no_ladder",
        "half_up_tier_no_vat",
        "no_rules_at_all",
    ]


_CASES = _load("pricing_cases.json")["cases"]
_PARITY = [
    (case["name"], code, product, case["expected"]["products"][code]["gross_list"], case["price_modifier"])
    for case in _CASES
    if case["price_modifier"]
    for code, product in case["products"].items()
    if product["tax"] == "21"
]


def _apply_modifier(net: Decimal, modifier: str) -> Decimal:
    # The BAPP channel modifier is a signed percent string such as "-5%":
    # modified = net * (1 + pct / 100), kept at 4dp like the ERP price column.
    pct = Decimal(modifier.rstrip("%"))
    return (net * (1 + pct / Decimal("100"))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@pytest.mark.parametrize("case_name,code,product,expected_gross,modifier", _PARITY, ids=[f"{c}-{p}" for c, p, *_ in _PARITY])
def test_gross_list_matches_store_for_21_percent(case_name, code, product, expected_gross, modifier):
    # Store side: gross_list = round_half_up(modified_net * 1.21, 2), e.g. 100 -> 95 -> 114.95, 70 -> 66.5 -> 80.465 -> 80.47.
    modified_net = _apply_modifier(Decimal(product["net"]), modifier)
    assert to_gross(modified_net, Decimal("0.21")) == Decimal(expected_gross)


def test_parity_selection_covers_every_21_percent_product():
    assert sorted(f"{c}-{p}" for c, p, *_ in _PARITY) == [
        "below_minimum-P",
        "below_minimum-Q",
        "category_ancestor_rule-U",
        "non_discountable_no_ladder-T",
        "worked_example-P",
        "worked_example-Q",
    ]
