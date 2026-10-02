"""
Calendarul fiscal Apple, calculat din regula, fara tabel de mentinut.

`GET /v1/financeReports` cere `filter[reportDate]=<an fiscal>-<indice lunar>` (01 = octombrie,
12 = septembrie), nu eticheta noastra; vezi `apple_report_date`. Regula Apple:

- anul fiscal `Y` se incheie in ULTIMA SAMBATA din septembrie a anului calendaristic `Y`
  si incepe a doua zi dupa sfarsitul anului fiscal precedent;
- fiecare trimestru are trei luni de 5-4-4 saptamani (oct=5, nov=4, dec=4, ian=5, ...);
- un an de 53 de saptamani (371 de zile) pune saptamana in plus in ULTIMA luna a Q1
  (decembrie are 5 saptamani), ca in FY2023, unde Q1 s-a incheiat pe 2022-12-31.

Cheia unei luni este eticheta ei `"YYYY-MM"`: oct..dec din anul fiscal `Y` poarta anul
calendaristic `Y-1`, ian..sep poarta `Y`. Calendarul e valabil din FY2010 incoace.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

#: primul an fiscal acceptat (istoricul de dinainte nu are sens pentru rapoartele financiare)
MIN_FISCAL_YEAR = 2010

#: Apple plateste la 33 de zile dupa inchiderea lunii fiscale (exceptii rare in noiembrie).
PAYMENT_DELAY_DAYS = 33

#: saptamani pe luna, in ordinea fiscala oct..sep (an de 52 de saptamani)
_WEEKS_PER_MONTH = (5, 4, 4, 5, 4, 4, 5, 4, 4, 5, 4, 4)
#: luna calendaristica a fiecarei luni fiscale, in aceeasi ordine
_LABEL_MONTHS = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
#: indexul lunii care primeste saptamana a 53-a (decembrie = ultima luna din Q1)
_EXTRA_WEEK_INDEX = 2

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def fiscal_year_end(fiscal_year: int) -> date:
    """Ultima sambata din septembrie a anului calendaristic `fiscal_year`."""
    last = date(fiscal_year, 9, 30)
    # weekday(): luni=0 .. sambata=5
    return last - timedelta(days=(last.weekday() - 5) % 7)


@lru_cache(maxsize=64)
def _fiscal_months(fiscal_year: int) -> tuple[tuple[str, date, date], ...]:
    start = fiscal_year_end(fiscal_year - 1) + timedelta(days=1)
    end = fiscal_year_end(fiscal_year)
    weeks = list(_WEEKS_PER_MONTH)
    length = (end - start).days + 1
    if length == 371:
        weeks[_EXTRA_WEEK_INDEX] += 1
    elif length != 364:  # pragma: no cover - regula garanteaza 364 sau 371
        raise ValueError(f"Anul fiscal Apple {fiscal_year} are {length} zile; regula cere 364 sau 371.")

    months: list[tuple[str, date, date]] = []
    cursor = start
    for label_month, week_count in zip(_LABEL_MONTHS, weeks, strict=True):
        label_year = fiscal_year - 1 if label_month >= 10 else fiscal_year
        month_end = cursor + timedelta(days=7 * week_count - 1)
        months.append((f"{label_year:04d}-{label_month:02d}", cursor, month_end))
        cursor = month_end + timedelta(days=1)
    return tuple(months)


def fiscal_months(fiscal_year: int) -> dict[str, tuple[date, date]]:
    """Lunile fiscale ale anului fiscal `fiscal_year`: eticheta -> (prima zi, ultima zi), inclusiv."""
    if fiscal_year < MIN_FISCAL_YEAR:
        raise ValueError(f"Calendarul fiscal Apple incepe cu FY{MIN_FISCAL_YEAR}; s-a cerut FY{fiscal_year}.")
    return {label: (start, end) for label, start, end in _fiscal_months(fiscal_year)}


def _fiscal_year_of_label(period: str) -> int:
    match = _PERIOD_RE.match(period or "")
    if not match:
        raise ValueError(f"Perioada fiscala Apple invalida: {period!r} (se asteapta YYYY-MM).")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Perioada fiscala Apple invalida: {period!r} (luna {month}).")
    return year + 1 if month >= 10 else year


def _parse_label(label: str) -> tuple[int, int]:
    match = _PERIOD_RE.match(label or "")
    if not match:
        raise ValueError(f"Perioada fiscala Apple invalida: {label!r} (se asteapta YYYY-MM).")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Perioada fiscala Apple invalida: {label!r} (luna {month}).")
    return year, month


def apple_report_date(period: str) -> str:
    """Eticheta noastra `YYYY-MM` -> `filter[reportDate]` Apple: `<an fiscal>-<indice lunar>`, 01 = octombrie."""
    year, month = _parse_label(period)
    month_index = (month - 10) % 12 + 1
    fiscal_year = year + 1 if month >= 10 else year
    return f"{fiscal_year:04d}-{month_index:02d}"


def period_from_apple_report_date(report_date: str) -> str:
    """Inversa lui `apple_report_date`: `<an fiscal>-<indice lunar>` -> eticheta noastra `YYYY-MM`."""
    fiscal_year, month_index = _parse_label(report_date)
    month = (month_index + 8) % 12 + 1
    label_year = fiscal_year - 1 if month >= 10 else fiscal_year
    return f"{label_year:04d}-{month:02d}"


def fiscal_range(period: str) -> tuple[date, date]:
    return fiscal_months(_fiscal_year_of_label(period))[period]


def fiscal_year_for(day: date) -> int:
    fiscal_year = day.year + 1 if day > fiscal_year_end(day.year) else day.year
    if fiscal_year < MIN_FISCAL_YEAR:
        raise ValueError(f"Ziua {day.isoformat()} e inainte de FY{MIN_FISCAL_YEAR}, primul an fiscal acceptat.")
    return fiscal_year


def fiscal_period_for(day: date) -> str:
    for period, (start, end) in fiscal_months(fiscal_year_for(day)).items():
        if start <= day <= end:
            return period
    raise AssertionError(f"Ziua {day.isoformat()} nu a cazut in nicio luna fiscala")  # pragma: no cover


def fiscal_periods_between(start: date, end: date) -> list[str]:
    """Lunile fiscale care acopera intervalul calendaristic [start, end], in ordine."""
    if end < start:
        return []
    periods: list[str] = []
    for fiscal_year in range(fiscal_year_for(start), fiscal_year_for(end) + 1):
        for period, (p_start, p_end) in fiscal_months(fiscal_year).items():
            if p_end >= start and p_start <= end:
                periods.append(period)
    return periods


def payment_date(period: str) -> date | None:
    try:
        _start, end = fiscal_range(period)
    except (ValueError, KeyError):
        return None
    return end + timedelta(days=PAYMENT_DELAY_DAYS)
