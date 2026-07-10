"""Unit tests for Okazii mappers (no API access required)."""

from __future__ import annotations

from bapp_connectors.providers.shop.okazii.mappers import order_from_okazii


def _order_payload(**billing_overrides) -> dict:
    """Minimal realistic export_orders payload for one order."""
    return {
        "id": 12345678,
        "createdAt": "2025-03-14T10:22:31+02:00",
        "updatedAt": "2025-03-14T10:22:31+02:00",
        "bids": [
            {
                "bidId": 1,
                "auctionUniqueId": 987654,
                "auctionTitle": "Produs test",
                "amount": 1,
                "itemPrice": {"amount": "49.99", "currency": "RON"},
                "status": "finalized",
                "paymentMethod": "ramburs",
            }
        ],
        "totalValue": {"amount": "49.99", "currency": "RON"},
        "buyerContact": {"firstName": "Ion", "lastName": "Popescu", "email": None, "phone": None},
        "billingInfo": {
            "firstName": "Ion",
            "lastName": "Popescu",
            "address": "Str. Exemplu 1",
            "city": "Bucuresti",
            "county": "Bucuresti",
            "zipcode": "010101",
            "company": "Firma SRL",
            "cui": "RO123456",
            **billing_overrides,
        },
        "deliveryAddress": None,
        "deliveryPrice": {"amount": "0", "currency": "RON"},
    }


def test_order_from_okazii_handles_null_billing_company_and_cui():
    """Historical orders carry JSON null for company/cui — must map to '' not crash."""
    order = order_from_okazii(_order_payload(company=None, cui=None))
    assert order.billing is not None
    assert order.billing.company_name == ""
    assert order.billing.vat_id == ""


def test_order_from_okazii_strips_billing_company_and_cui():
    order = order_from_okazii(_order_payload(company=" Firma SRL ", cui=" RO123456 "))
    assert order.billing is not None
    assert order.billing.company_name == "Firma SRL"
    assert order.billing.vat_id == "RO123456"
