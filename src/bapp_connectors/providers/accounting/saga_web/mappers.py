"""
SAGA Web mappers: JSON envelope, import report text and the XML reports.

Pure functions only; the client returns raw bodies and the adapter calls these.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

from bapp_connectors.core.dto import Article, ImportProblem, StockLine, TrialBalanceLine

# ── Scalars ──


def saga_date(day: date) -> str:
    """Format a date the way SAGA Web expects it: ``dd.MM.yyyy``."""
    return day.strftime("%d.%m.%Y")


def to_decimal(text: str | None, default: Decimal = Decimal(0)) -> Decimal:
    """Parse a SAGA number (``"3142,9"`` or ``"3142.9"``); blank or invalid → ``default``."""
    if text is None:
        return default
    cleaned = text.strip().replace(",", ".")
    if not cleaned:
        return default
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return default


def _optional_decimal(text: str | None) -> Decimal | None:
    if text is None or not text.strip():
        return None
    value = to_decimal(text, default=Decimal("NaN"))
    return None if value.is_nan() else value


# ── JSON envelope ──


def parse_envelope(body: str) -> tuple[bool, str, str]:
    """Read ``{success, message|error, data}``; a non-JSON body → ``(False, body[:300], "")``."""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return False, (body or "")[:300], ""
    if not isinstance(payload, dict):
        return False, (body or "")[:300], ""
    success = bool(payload.get("success"))
    message = payload.get("message") or payload.get("error") or ""
    data = payload.get("data")
    return success, str(message), "" if data is None else str(data)


# ── Import report ──

_INVOICE_RE = re.compile(r"^\s*Factura\s+(\d+)\.?\s*$")
_DOC_RE = re.compile(r"^\s*NR_DOC:(.*)$")
_ERROR_RE = re.compile(r"^\s*(Eroare.*)$")


def parse_report(text: str) -> list[ImportProblem]:
    """One ``ImportProblem`` per ``NR_DOC:`` block of a SAGA "Raport Import" text."""
    problems: list[ImportProblem] = []
    index: int | None = None
    current: dict | None = None

    def flush() -> None:
        if current is not None:
            problems.append(
                ImportProblem(
                    index=current["index"],
                    document_number=current["document_number"],
                    message="; ".join(current["errors"]),
                )
            )

    for line in (text or "").splitlines():
        if match := _INVOICE_RE.match(line):
            index = int(match.group(1))
            continue
        if match := _DOC_RE.match(line):
            flush()
            current = {"index": index, "document_number": match.group(1).strip(), "errors": []}
            continue
        if current is not None and (match := _ERROR_RE.match(line)):
            current["errors"].append(match.group(1).strip())
    flush()
    return problems


# ── XML reports ──


def _parse_xml(xml: str) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("XML invalid") from exc


def _text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


_STOCK_TEXT = {
    "GESTIUNE": "warehouse",
    "DEN_GEST": "warehouse_name",
    "DENUMIRE": "name",
    "COD_ART": "article_code",
    "COD_BARE": "barcode",
    "GRUPA": "group",
    "UM": "unit",
    "TIP": "type_code",
    "DEN_TIP": "type_name",
    "CONT": "account",
    "TEXT_SUPL": "extra_text",
}
_STOCK_DECIMAL = {
    "CANT_MIN": "qty_min",
    "CANT_INT": "qty_in",
    "CANT_IES": "qty_out",
    "CANT_INIT": "qty_initial",
    "CANT_FIN": "qty_final",
    "GREUTATE": "weight",
    "PRET_MEDIU": "avg_price",
    "VAL_INIT": "value_initial",
    "VAL_INT": "value_in",
    "VAL_IES": "value_out",
    "VALOARE": "value",
    "COMANDAT": "ordered",
    "COM_INT": "ordered_in",
    "DISPONIBIL": "available",
}


def parse_stock_report(xml: str) -> list[StockLine]:
    """``<Situatie>/<LinieSituatieXML>`` → ``StockLine`` list."""
    root = _parse_xml(xml)
    lines: list[StockLine] = []
    for row in root.iter("LinieSituatieXML"):
        fields: dict = {attr: _text(row, tag) for tag, attr in _STOCK_TEXT.items()}
        fields.update({attr: to_decimal(_text(row, tag)) for tag, attr in _STOCK_DECIMAL.items()})
        fields["vat"] = _optional_decimal(_text(row, "TVA"))
        fields["sellable"] = _text(row, "VANDABIL") == "1"
        lines.append(StockLine(**fields))
    return lines


_BALANCE_DECIMAL = {
    "DEB_INIT": "debit_initial",
    "CRED_INIT": "credit_initial",
    "DEB_PREC": "debit_previous",
    "CRED_PREC": "credit_previous",
    "RULAJ_D": "debit_turnover",
    "RULAJ_C": "credit_turnover",
    "TOTAL_DEB": "debit_total",
    "TOTAL_CRED": "credit_total",
    "FIN_D": "debit_final",
    "FIN_C": "credit_final",
}


def parse_trial_balance(xml: str) -> list[TrialBalanceLine]:
    """``<Balanta>/<LinieBalantaXML>`` → ``TrialBalanceLine`` list."""
    root = _parse_xml(xml)
    lines: list[TrialBalanceLine] = []
    for row in root.iter("LinieBalantaXML"):
        fields: dict = {attr: to_decimal(_text(row, tag)) for tag, attr in _BALANCE_DECIMAL.items()}
        lines.append(
            TrialBalanceLine(
                account=_text(row, "CONT"),
                name=_text(row, "DENUMIRE"),
                kind=_text(row, "TIP"),
                **fields,
            )
        )
    return lines


def parse_article(xml: str) -> Article | None:
    """``<Articol>`` → ``Article``; ``None`` when the root element is something else."""
    root = _parse_xml(xml)
    if root.tag != "Articol":
        return None
    return Article(
        name=_text(root, "Denumire"),
        vat=_optional_decimal(_text(root, "TVA")),
        unit=_text(root, "UM"),
        price1=_optional_decimal(_text(root, "Pret_Vanzare1")),
        price1_vat=_optional_decimal(_text(root, "Pret_Vanzare1_cuTVA")),
        price2=_optional_decimal(_text(root, "Pret_Vanzare2")),
        price2_vat=_optional_decimal(_text(root, "Pret_Vanzare2_cuTVA")),
        barcode=_text(root, "Cod_Bare"),
        nc_code=_text(root, "Cod_NC"),
        cpv_code=_text(root, "Cod_CPV"),
        info=_text(root, "Informatii_Suplimentare"),
        own_code=_text(root, "Cod_Propriu"),
    )
