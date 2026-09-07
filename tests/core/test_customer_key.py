import json

from bapp_connectors.core.pricing.customer_key import CUSTOMER_KEY_CASES_PATH, normalise_customer_key


def test_every_shipped_case_normalises_as_recorded():
    cases = json.loads(CUSTOMER_KEY_CASES_PATH.read_text())["cases"]
    assert cases, "the fixture must not be empty"
    for case in cases:
        assert normalise_customer_key(case["raw"]) == case["key"], case["raw"]


def test_normalisation_is_idempotent():
    for raw in ("RO 12.345.678", "j40/1234/2020", ""):
        once = normalise_customer_key(raw)
        assert normalise_customer_key(once) == once
