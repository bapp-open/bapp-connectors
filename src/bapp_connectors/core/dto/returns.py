"""Retururi / rambursari citite din magazine (read-only)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO


class ReturnKind(StrEnum):
    RETURN = "return"              # retur fizic (eMAG RMA, Trendyol claim)
    REFUND = "refund"              # doar rambursare (WooCommerce)
    ORDER_STATUS = "order_status"  # doar statusul comenzii (Okazii "returned")


class ShopReturnRefund(BaseDTO):
    amount: Decimal
    currency: str = ""
    type: str = ""
    status: str = ""
    at: datetime | None = None
    estimated: bool = False


class ShopReturnLine(BaseDTO):
    external_line_id: str = ""
    sku: str = ""
    barcode: str = ""
    name: str = ""
    quantity: Decimal = Decimal("1")
    unit_price: Decimal | None = None
    reason_code: str = ""
    reason_label: str = ""
    customer_note: str = ""
    unit_statuses: list[str] = []


class ShopReturn(BaseDTO):
    external_id: str
    external_order_id: str = ""
    kind: ReturnKind = ReturnKind.RETURN
    status_raw: str = ""
    status_label: str = ""
    requested_at: datetime | None = None
    picked_up_at: datetime | None = None
    customer_name: str = ""
    comment: str = ""
    awb: str = ""
    awb_ref: str = ""
    courier: str = ""
    tracking_url: str = ""
    refund: ShopReturnRefund | None = None
    history: list[dict] = []
    lines: list[ShopReturnLine] = []
    raw: dict = {}
