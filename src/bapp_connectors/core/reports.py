"""
Helpere pentru providerii ale caror date vin ca rapoarte-fisier (TSV gzip, CSV in ZIP)
si pentru paginarea pe perioade (o pagina = un fisier de zi sau de luna).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def decode_text(data: bytes) -> str:
    """Decodeaza dupa BOM: UTF-16 (Google Play reviews), UTF-8 cu BOM, altfel UTF-8."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    return data.decode("utf-8", errors="replace")


def csv_rows(text: str, delimiter: str = ",") -> list[dict[str, str]]:
    """Randurile unui CSV/TSV ca dict-uri cu chei si valori curatate; liniile goale sunt sarite."""
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k is not None}
        if any(row.values()):
            rows.append(row)
    return rows


def gunzip_tsv_rows(content: bytes) -> list[dict[str, str]]:
    """Raport Apple: gzip cu TSV; randurile de subsol `Total...` sunt sarite."""
    text = decode_text(gzip.decompress(content))
    rows = csv_rows(text, delimiter="\t")
    return [row for row in rows if not next(iter(row.values()), "").startswith("Total")]


_FINANCE_PREAMBLE_KEYS = {"Vendor Name", "Start Date", "End Date"}
_FINANCE_MIN_HEADER_CELLS = 10


def parse_apple_finance_detail(content: bytes) -> tuple[dict[str, str], list[dict[str, str]]]:
    """
    FINANCE_DETAIL Apple: gzip cu TSV de forma preambul (`Vendor Name`/`Start Date`/`End Date`),
    antet, randuri de date (cu o celula goala la coada), apoi o sectiune de totaluri care incepe
    cu `Country Of Sale`. Intoarce `(preambul, randuri)`; totalurile sunt ignorate.
    """
    text = decode_text(gzip.decompress(content))
    preamble: dict[str, str] = {}
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for cells in csv.reader(io.StringIO(text), delimiter="\t"):
        if not any(c.strip() for c in cells):
            continue
        cells = [c.strip() for c in cells]
        if header is None:
            if len(cells) == 2 and cells[0] in _FINANCE_PREAMBLE_KEYS:
                preamble[cells[0]] = cells[1]
            elif len(cells) >= _FINANCE_MIN_HEADER_CELLS:
                header = cells
            continue
        if cells[0].lower() == "country of sale" or len(cells) < _FINANCE_MIN_HEADER_CELLS:
            break
        rows.append(dict(zip(header, cells, strict=False)))
    return preamble, rows


def unzip_csv_rows(content: bytes, member_suffix: str = ".csv") -> list[dict[str, str]]:
    """Raport Google Play: ZIP cu un CSV (UTF-8 sau UTF-16, dupa BOM)."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(member_suffix)]
        if not names:
            return []
        data = archive.read(names[0])
    return csv_rows(decode_text(data))


def to_decimal(value: str | None, default: Decimal = Decimal("0")) -> Decimal:
    """`""`/None -> default; accepta spatii si virgula zecimala."""
    if value is None:
        return default
    text = str(value).strip().replace(" ", "")
    if not text:
        return default
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def stable_key(*parts: object) -> str:
    """Cheie deterministica (sha1 hex) pentru identitatea unui rand de raport."""
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()  # sha1: identitate, nu securitate


def daily_page(start: date, end: date, cursor: str | None) -> tuple[date, str | None]:
    """Ziua de adus pentru pagina curenta si cursorul paginii urmatoare (None = ultima)."""
    day = date.fromisoformat(cursor) if cursor else start
    following = day + timedelta(days=1)
    return day, (following.isoformat() if following <= end else None)


def monthly_page(start: date, end: date, cursor: str | None) -> tuple[tuple[int, int], str | None]:
    """Luna `(an, luna)` de adus si cursorul `YYYY-MM` al lunii urmatoare (None = ultima)."""
    if cursor:
        year, month = (int(p) for p in cursor.split("-"))
    else:
        year, month = start.year, start.month
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    has_next = (next_year, next_month) <= (end.year, end.month)
    return (year, month), (f"{next_year:04d}-{next_month:02d}" if has_next else None)
