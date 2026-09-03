"""Fixture parity: the JSON files under the package are the cross-repo contract."""
import json
from pathlib import Path

FIXTURES = Path("src/bapp_connectors/providers/shop/bapp_store/fixtures")


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
