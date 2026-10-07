"""The customer's note on an order, normalised across shops.

Every platform names it differently — WooCommerce `customer_note`, eMAG and Gomag
`observation`, Shopify `note` — and some have no such field at all. Each mapper says which
keys its own payload uses; nothing is sniffed generically, so a key that means something
else elsewhere cannot leak in.

Measured on live shops (2026-10-07) for woocommerce, emag and gomag; okazii and trendyol
answer with no note-like key at all, which is why they pass nothing here.
"""

from __future__ import annotations

from typing import Any


def customer_note_from(data: dict[str, Any] | None, *keys: str) -> str:
    """The first of `keys` that holds text, stripped. Empty when none does.

    Values are taken as they come: a shop that returns `None` for "no note" and one that
    returns `""` mean the same thing here.
    """
    for key in keys:
        value = (data or {}).get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
