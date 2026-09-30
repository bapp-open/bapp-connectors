"""Altex RMA -> ShopReturn.

An RMA line carries only the catalog product id, the action and the reason — no SKU,
quantity or price — so they are filled from the order line with the same product id.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from bapp_connectors.core.dto import ReturnKind, ReturnReason, ShopReturn, ShopReturnLine, ShopReturnRefund

RMA_STATUS_LABELS = {1: "Registered", 2: "In Progress", 3: "Received", 4: "Resolved", 5: "Cancelled",
                     6: "Visualized"}

# Reason codes from the spec, onto the unified ReturnReason.
RMA_REASONS: dict[int, tuple[str, ReturnReason]] = {
    0: ("Other", ReturnReason.OTHER),
    1: ("Not satisfied of the product", ReturnReason.CHANGED_MIND),
    2: ("The product is defective", ReturnReason.DEFECTIVE),
    3: ("Incomplete accessories", ReturnReason.MISSING_PARTS),
    4: ("Damaged parcel caused by the transport", ReturnReason.DAMAGED),
    5: ("Return sealed product", ReturnReason.CHANGED_MIND),
    6: ("Chose wrong product", ReturnReason.ORDERED_BY_MISTAKE),
    7: ("Received wrong product", ReturnReason.WRONG_ITEM),
    8: ("Better price product", ReturnReason.CHANGED_MIND),
    9: ("Denial", ReturnReason.NOT_DELIVERED),
    10: ("Refuse delivery", ReturnReason.NOT_DELIVERED),
}
MONEY_BACK = 2


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dec(value) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def rma_date(value) -> datetime | None:
    """ISO with offset in real answers, a unix int in the doc example."""
    if isinstance(value, (int, float)):
        from datetime import UTC
        return datetime.fromtimestamp(value, tz=UTC)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def return_from_rma(rma: dict, order: dict | None = None) -> ShopReturn:
    lines_by_product = {str(line.get("product_id")): line for line in (order or {}).get("products") or []}
    lines, refund_total = [], Decimal("0")
    for item in rma.get("products") or []:
        reason_code = _int(item.get("reason"))
        label, reason = RMA_REASONS.get(reason_code, (str(item.get("reason") or ""), ReturnReason.OTHER))
        order_line = lines_by_product.get(str(item.get("id")), {})
        price = _dec(order_line.get("selling_price") or order_line.get("catalog_price"))
        if price is not None and _int(item.get("action")) == MONEY_BACK:
            refund_total += price
        lines.append(ShopReturnLine(
            external_line_id=str(item.get("rma_line_id") or ""),
            sku=str(order_line.get("seller_product_code") or ""),
            name=str(item.get("name") or order_line.get("name") or ""),
            quantity=Decimal("1"),  # an RMA line is one unit; the API has no quantity
            unit_price=price,
            reason_code=str(item.get("reason") if item.get("reason") is not None else ""),
            reason_label=label,
            reason=reason,
        ))
    status = _int(rma.get("rma_status"))
    return ShopReturn(
        external_id=str(rma.get("rma_id") or ""),
        external_order_id=str(rma.get("order_id") or ""),
        kind=ReturnKind.RETURN,
        status_raw=str(rma.get("rma_status") or ""),
        status_label=RMA_STATUS_LABELS.get(status, str(rma.get("rma_status") or "")),
        requested_at=rma_date(rma.get("created_date")),
        customer_name=str(rma.get("customer_name") or ""),
        refund=ShopReturnRefund(amount=refund_total, currency="RON", type="money_back", estimated=True)
        if refund_total else None,
        lines=lines,
        raw={k: rma.get(k) for k in ("customer_street", "customer_city", "customer_region", "bank_name",
                                      "bank_iban", "bank_account_owner")},
    )
