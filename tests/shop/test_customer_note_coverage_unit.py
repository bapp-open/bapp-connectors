"""Every shop maps the customer's note, or says in writing why it cannot.

The note the customer leaves on an order ("ridicăm noi", "sunați înainte") is the kind of
thing that changes what the warehouse does. It used to reach BAPP through the legacy
WooCommerce connector and stopped at the new generation, silently, because nothing required
a mapper to carry it.

So this is a gate, not a style check: a shop provider added tomorrow either fills
`Order.customer_note` or lands in `WITHOUT_A_NOTE_FIELD` with a reason — a decision someone
made, not a field someone forgot.
"""

from __future__ import annotations

import pathlib
import re

SHOP_PROVIDERS = pathlib.Path(__file__).resolve().parents[2] / "src/bapp_connectors/providers/shop"

#: Their order payload has no note-like key at all — checked on live shops (2026-10-07):
#: the connections for both answered with nothing resembling a note.
WITHOUT_A_NOTE_FIELD = {
    "okazii": "payload-ul comenzii n-are nicio cheie de nota (verificat pe conexiunea 29)",
    "trendyol": "payload-ul comenzii n-are nicio cheie de nota (verificat pe conexiunile 28, 42, 43)",
}


def _mappers_building_orders() -> dict[str, str]:
    """Each shop provider's mappers.py that constructs an `Order(...)`, by provider name."""
    found = {}
    for path in sorted(SHOP_PROVIDERS.glob("*/mappers.py")):
        source = path.read_text()
        if re.search(r"\breturn Order\(", source):
            found[path.parent.name] = source
    return found


def test_every_shop_provider_has_an_order_mapper_we_know_about():
    providers = set(_mappers_building_orders())
    assert providers, "no shop order mappers found — did the layout change?"
    assert WITHOUT_A_NOTE_FIELD.keys() <= providers


def test_every_order_mapper_carries_the_customer_note():
    missing = [
        provider
        for provider, source in _mappers_building_orders().items()
        if provider not in WITHOUT_A_NOTE_FIELD and "customer_note=customer_note_from(" not in source
    ]
    assert not missing, (
        "these shops drop the customer's note: "
        + ", ".join(sorted(missing))
        + " — map it with `customer_note_from(data, <cheile lor>)`, or add the provider to "
        "WITHOUT_A_NOTE_FIELD with the reason."
    )


def test_the_exceptions_are_real_providers_that_still_do_not_map_it():
    """Keeps the list honest: once a shop starts carrying a note, it leaves the list."""
    mappers = _mappers_building_orders()
    stale = [
        provider
        for provider in WITHOUT_A_NOTE_FIELD
        if "customer_note=customer_note_from(" in mappers.get(provider, "")
    ]
    assert not stale, f"{stale} map the note now — drop them from WITHOUT_A_NOTE_FIELD"
