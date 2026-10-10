"""Decontul Trendyol isi poarta moneda; o comanda in EUR (Grecia/Bulgaria) se deconteaza in RON."""

from decimal import Decimal

from bapp_connectors.providers.shop.trendyol.mappers import settlement_from_trendyol


def _row(**overrides) -> dict:
    row = {
        "id": "13584511227",
        "transactionType": "Sale",
        "transactionDate": 1780700000000,
        "credit": 101.81,
        "debt": 0,
        "orderNumber": "11284521240",
        "paymentOrderId": 75122550,
        "country": "Bulgaria",
        "currency": "RON",
    }
    row.update(overrides)
    return row


def test_currency_comes_from_the_settlement_row():
    tx = settlement_from_trendyol(_row(), "Sale")
    assert tx.currency == "RON"
    assert tx.credit == Decimal("101.81")
    assert tx.order_id == "11284521240"


def test_eur_settlement_keeps_eur():
    assert settlement_from_trendyol(_row(currency="EUR"), "Sale").currency == "EUR"


def test_missing_currency_stays_empty():
    row = _row()
    del row["currency"]
    assert settlement_from_trendyol(row, "Sale").currency == ""
