"""Helperele comune pentru rapoarte-fisier (gzip TSV, zip CSV, cursoare pe perioade)."""

from __future__ import annotations

import gzip
import io
import zipfile
from datetime import date
from decimal import Decimal

from bapp_connectors.core.reports import (
    csv_rows,
    daily_page,
    decode_text,
    gunzip_tsv_rows,
    monthly_page,
    stable_key,
    to_decimal,
    unzip_csv_rows,
)


def test_decode_text_detects_utf16_bom():
    assert decode_text("abc".encode("utf-16")) == "abc"
    assert decode_text("abc".encode("utf-8-sig")) == "abc"
    assert decode_text(b"abc") == "abc"


def test_csv_rows_strips_and_skips_blank_lines():
    rows = csv_rows("A, B\n1 , 2\n\n3,4\n")
    assert rows == [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}]


def test_gunzip_tsv_rows_skips_total_footer():
    text = "Provider\tUnits\nAPPLE\t2\nTotal_Units\t2\n"
    rows = gunzip_tsv_rows(gzip.compress(text.encode("utf-8")))
    assert rows == [{"Provider": "APPLE", "Units": "2"}]


def test_unzip_csv_rows_reads_first_csv_member():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "x")
        archive.writestr("salesreport_202609.csv", "Order Number,Item Price\nGPA.1,10.00\n")
    rows = unzip_csv_rows(buffer.getvalue())
    assert rows == [{"Order Number": "GPA.1", "Item Price": "10.00"}]


def test_unzip_csv_rows_decodes_utf16_member():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("reviews.csv", "Star Rating,Review Text\n5,Super\n".encode("utf-16"))
    rows = unzip_csv_rows(buffer.getvalue())
    assert rows[0]["Review Text"] == "Super"


def test_to_decimal_handles_blank_and_comma():
    assert to_decimal("") == Decimal("0")
    assert to_decimal(None) == Decimal("0")
    assert to_decimal(" 1,5 ") == Decimal("1.5")
    assert to_decimal("-3.25") == Decimal("-3.25")


def test_stable_key_is_deterministic():
    assert stable_key("a", 1, None) == stable_key("a", 1, None)
    assert stable_key("a", 1) != stable_key("a", 2)
    assert len(stable_key("x")) == 40


def test_daily_page_walks_days_then_stops():
    start, end = date(2026, 9, 1), date(2026, 9, 3)
    assert daily_page(start, end, None) == (date(2026, 9, 1), "2026-09-02")
    assert daily_page(start, end, "2026-09-02") == (date(2026, 9, 2), "2026-09-03")
    assert daily_page(start, end, "2026-09-03") == (date(2026, 9, 3), None)


def test_monthly_page_walks_months_then_stops():
    start, end = date(2026, 8, 15), date(2026, 10, 2)
    assert monthly_page(start, end, None) == ((2026, 8), "2026-09")
    assert monthly_page(start, end, "2026-09") == ((2026, 9), "2026-10")
    assert monthly_page(start, end, "2026-10") == ((2026, 10), None)
