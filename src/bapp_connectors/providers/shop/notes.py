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
        # O lista sau un dict nu sint o nota, sint alta structura cu acelasi nume: Gomag
        # tine sub `note` istoricul comentariilor interne, iar `str([])` ar fi intors
        # textul "[]" ca observatie a clientului pe FIECARE comanda.
        if value is None or isinstance(value, (list, dict, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def staff_notes_from(entries: Any, comment_key: str = "comment", user_key: str = "user") -> str:
    """Notele interne ale magazinului, ca text de pus in „Mentiuni".

    Gomag le tine ca lista de `{comment, user, time}` — scrise de oamenii din magazin
    („Proforma trimisa", „DE ANUNTAT CAND AJUNG PRODUSELE"), nu de client. Ora ramine in
    payload-ul brut: aici conteaza cine si ce a scris, pe cite un rind.
    """
    if not isinstance(entries, (list, tuple)):
        return ""
    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        comment = str(entry.get(comment_key) or "").strip()
        if not comment:
            continue
        who = str(entry.get(user_key) or "").strip()
        lines.append(f"{who}: {comment}" if who else comment)
    return "\n".join(lines)
