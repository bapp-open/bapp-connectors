"""The one rule by which a customer is keyed across the panel and the store."""

from __future__ import annotations

from pathlib import Path

CUSTOMER_KEY_CASES_PATH = Path(__file__).with_name("fixtures") / "customer_key_cases.json"


def normalise_customer_key(raw: str) -> str:
    """Uppercase alphanumerics, with a leading ISO country prefix removed.

    A fiscal code reaches the store typed by a buyer and reaches the panel typed by an
    accountant. `RO 12.345.678` and `12345678` are the same company and must key alike.
    A two-letter prefix is only a country marker when the rest is all digits: `RO123AB456`
    is a code that happens to start with two letters.
    """
    compact = "".join(ch for ch in raw.upper() if ch.isascii() and ch.isalnum())
    if len(compact) > 2 and compact[:2].isalpha() and compact[2:].isdigit():
        return compact[2:]
    return compact
