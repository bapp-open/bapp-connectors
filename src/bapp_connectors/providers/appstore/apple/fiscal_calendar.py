"""
Calendarul fiscal Apple.

Apple inchide lunile pe un calendar 4-4-5 saptamani (unele ani au 53 de saptamani),
iar `GET /v1/financeReports` cere `filter[reportDate]=YYYY-MM` cu luna FISCALA,
nu cea calendaristica. Cheia de mai jos este exact valoarea trimisa in API.

Sursa: calendarul fiscal din App Store Connect > Payments and Financial Reports.
Se adauga cate un an fiscal inainte; testul `test_calendar_covers_next_twelve_months`
pica cu un an inainte sa expire.
"""

from __future__ import annotations

from datetime import date, timedelta

#: perioada fiscala -> (prima zi, ultima zi), inclusiv
FISCAL_MONTHS: dict[str, tuple[date, date]] = {
    # Anul fiscal 2026 (52 saptamani)
    "2025-10": (date(2025, 9, 28), date(2025, 11, 1)),
    "2025-11": (date(2025, 11, 2), date(2025, 11, 29)),
    "2025-12": (date(2025, 11, 30), date(2025, 12, 27)),
    "2026-01": (date(2025, 12, 28), date(2026, 1, 31)),
    "2026-02": (date(2026, 2, 1), date(2026, 2, 28)),
    "2026-03": (date(2026, 3, 1), date(2026, 3, 28)),
    "2026-04": (date(2026, 3, 29), date(2026, 5, 2)),
    "2026-05": (date(2026, 5, 3), date(2026, 5, 30)),
    "2026-06": (date(2026, 5, 31), date(2026, 6, 27)),
    "2026-07": (date(2026, 6, 28), date(2026, 8, 1)),
    "2026-08": (date(2026, 8, 2), date(2026, 8, 29)),
    "2026-09": (date(2026, 8, 30), date(2026, 9, 26)),
    # Anul fiscal 2027 (53 saptamani: Q1 are o saptamana in plus)
    "2026-10": (date(2026, 9, 27), date(2026, 10, 31)),
    "2026-11": (date(2026, 11, 1), date(2026, 11, 28)),
    "2026-12": (date(2026, 11, 29), date(2027, 1, 2)),
    "2027-01": (date(2027, 1, 3), date(2027, 1, 30)),
    "2027-02": (date(2027, 1, 31), date(2027, 2, 27)),
    "2027-03": (date(2027, 2, 28), date(2027, 4, 3)),
    "2027-04": (date(2027, 4, 4), date(2027, 5, 1)),
    "2027-05": (date(2027, 5, 2), date(2027, 6, 5)),
    "2027-06": (date(2027, 6, 6), date(2027, 7, 3)),
    "2027-07": (date(2027, 7, 4), date(2027, 7, 31)),
    "2027-08": (date(2027, 8, 1), date(2027, 8, 28)),
    "2027-09": (date(2027, 8, 29), date(2027, 10, 2)),
}

#: Apple plateste la 33 de zile dupa inchiderea lunii fiscale (exceptii rare in noiembrie).
PAYMENT_DELAY_DAYS = 33


def fiscal_range(period: str) -> tuple[date, date]:
    return FISCAL_MONTHS[period]


def fiscal_period_for(day: date) -> str:
    for period, (start, end) in FISCAL_MONTHS.items():
        if start <= day <= end:
            return period
    raise KeyError(f"Ziua {day.isoformat()} nu e acoperita de calendarul fiscal Apple; adauga anul fiscal.")


def fiscal_periods_between(start: date, end: date) -> list[str]:
    """Lunile fiscale care acopera intervalul calendaristic [start, end], in ordine."""
    return [period for period, (p_start, p_end) in sorted(FISCAL_MONTHS.items()) if p_end >= start and p_start <= end]


def payment_date(period: str) -> date | None:
    if period not in FISCAL_MONTHS:
        return None
    return FISCAL_MONTHS[period][1] + timedelta(days=PAYMENT_DELAY_DAYS)
