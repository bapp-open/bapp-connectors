import datetime
from decimal import Decimal
from pathlib import Path

from bapp_connectors.providers.accounting.saga_web import mappers

FIX = Path(__file__).parent / "fixtures"


def test_parse_envelope_success_and_error_keys():
    assert mappers.parse_envelope('{"success": true, "message": "", "data": "174852"}') == (True, "", "174852")
    assert mappers.parse_envelope('{"success": false, "error": "Nu ati trimis un cod de articol valid"}') == (
        False,
        "Nu ati trimis un cod de articol valid",
        "",
    )
    assert mappers.parse_envelope("<html>") == (False, "<html>", "")


def test_parse_report_two_problems():
    problems = mappers.parse_report((FIX / "raport_207.txt").read_text())
    assert [p.document_number for p in problems] == ["A100", "A1002"]
    assert problems[0].index == 1 and problems[1].index == 3
    assert problems[0].message == "Eroare antet: Factura a fost importata sau operata manual deja."
    assert problems[1].message == "Eroare: Completati clientul."


def test_parse_report_strips_document_number():
    problems = mappers.parse_report("Factura 2.\n     NR_DOC:  ras 12 \n     Eroare: X.\n")
    assert problems[0].document_number == "ras 12"


def test_parse_stock_report():
    lines = mappers.parse_stock_report((FIX / "situatie.xml").read_text())
    assert len(lines) == 1
    line = lines[0]
    assert line.warehouse == "0001" and line.article_code == "00000001" and line.sellable is True
    assert (
        line.qty_final == Decimal("136") and line.avg_price == Decimal("40.6675") and line.value == Decimal("5530.78")
    )


def test_parse_trial_balance():
    lines = mappers.parse_trial_balance((FIX / "balanta.xml").read_text())
    assert lines[0].account == "371" and lines[0].name == "MARFURI" and lines[0].kind == "A"
    assert lines[0].debit_initial == Decimal("-4") and lines[0].debit_final == Decimal("123456")


def test_parse_article():
    art = mappers.parse_article((FIX / "articol.xml").read_text())
    assert (
        art.name == "ARTICOL"
        and art.vat == Decimal("11")
        and art.price1_vat == Decimal("110")
        and art.barcode == "692648521232"
    )
    assert art.nc_code == "" and art.info == "Acesta este un exemplu"
    assert mappers.parse_article("<Altceva/>") is None


def test_saga_date_and_decimal():
    assert mappers.saga_date(datetime.date(2026, 1, 5)) == "05.01.2026"
    assert mappers.to_decimal(" 3142,9 ") == Decimal("3142.9")
    assert mappers.to_decimal("") == Decimal(0)


def test_parse_report_three_problems_repeated_index():
    problems = mappers.parse_report((FIX / "raport_207_trei.txt").read_text())
    assert [(p.index, p.document_number) for p in problems] == [(1, "A100"), (1, "A101"), (3, "A102")]
    assert problems[1].message == "Eroare antet: Data scadenta este anterioara datei documentului."
    assert problems[2].message == "Eroare: Completati clientul."


def test_parse_report_error_before_doc_number_stays_on_its_invoice():
    problems = mappers.parse_report("Factura 1.\n NR_DOC: A1\n Eroare: x\nFactura 2.\n Eroare: y\n NR_DOC: A2\n")
    assert [(p.index, p.document_number, p.message) for p in problems] == [
        (1, "A1", "Eroare: x"),
        (2, "A2", "Eroare: y"),
    ]


def test_parse_report_error_without_doc_number_is_kept():
    problems = mappers.parse_report("Factura 1.\n Eroare antet: fara numar\n")
    assert [(p.index, p.document_number, p.message) for p in problems] == [(1, "", "Eroare antet: fara numar")]


def test_to_decimal_rejects_invalid_and_non_finite():
    import pytest

    for bad in ("1.234,56", "abc", "NaN", "Infinity", "-inf"):
        with pytest.raises(ValueError):
            mappers.to_decimal(bad)
    assert mappers.to_decimal("   ") == Decimal(0)
    assert mappers.to_decimal(None, Decimal(5)) == Decimal(5)
