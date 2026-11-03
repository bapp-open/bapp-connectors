"""
DTO-uri normalizate pentru programele de contabilitate (SAGA Web).

Importul primeste fisiere (XML) si raspunde cu un ImportResult; situatiile (stocuri,
balanta, articol) sunt citite ca linii normalizate.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO


class ImportStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class ImportProblem(BaseDTO):
    index: int | None = None
    document_number: str = ""
    message: str


class ImportResult(BaseDTO):
    status: ImportStatus
    http_status: int
    message: str = ""
    report: str = ""
    problems: list[ImportProblem] = []


class StockLine(BaseDTO):
    warehouse: str
    warehouse_name: str
    article_code: str
    name: str
    barcode: str = ""
    group: str = ""
    unit: str = ""
    type_code: str = ""
    type_name: str = ""
    vat: Decimal | None = None
    account: str = ""
    sellable: bool = True
    qty_min: Decimal = Decimal(0)
    qty_in: Decimal = Decimal(0)
    qty_out: Decimal = Decimal(0)
    qty_initial: Decimal = Decimal(0)
    qty_final: Decimal = Decimal(0)
    weight: Decimal = Decimal(0)
    avg_price: Decimal = Decimal(0)
    value_initial: Decimal = Decimal(0)
    value_in: Decimal = Decimal(0)
    value_out: Decimal = Decimal(0)
    value: Decimal = Decimal(0)
    ordered: Decimal = Decimal(0)
    ordered_in: Decimal = Decimal(0)
    available: Decimal = Decimal(0)
    extra_text: str = ""


class TrialBalanceLine(BaseDTO):
    account: str
    name: str
    kind: str = ""
    debit_initial: Decimal = Decimal(0)
    credit_initial: Decimal = Decimal(0)
    debit_previous: Decimal = Decimal(0)
    credit_previous: Decimal = Decimal(0)
    debit_turnover: Decimal = Decimal(0)
    credit_turnover: Decimal = Decimal(0)
    debit_total: Decimal = Decimal(0)
    credit_total: Decimal = Decimal(0)
    debit_final: Decimal = Decimal(0)
    credit_final: Decimal = Decimal(0)


class Article(BaseDTO):
    name: str
    vat: Decimal | None = None
    unit: str = ""
    price1: Decimal | None = None
    price1_vat: Decimal | None = None
    price2: Decimal | None = None
    price2_vat: Decimal | None = None
    barcode: str = ""
    nc_code: str = ""
    cpv_code: str = ""
    info: str = ""
    own_code: str = ""
