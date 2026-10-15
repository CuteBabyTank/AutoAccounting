import io
import zipfile
from datetime import date

import fitz

from app.services.accounting.outgoing_2307 import build_zip, payee_forms

COMPANY = {"registered_name": "Juan's Cloth Trading", "tin": "123456789", "branch_code": "00000",
           "address": "Quiapo, Manila", "zip_code": "1001"}
Q3 = (date(2026, 7, 1), date(2026, 9, 30))


def _row(tin, name, atc, nature, m1, m3, base, tax):
    return {"key": f"{tin or name}|{atc}", "tin": tin, "name": name, "address": "Makati", "atc": atc,
            "nature": nature, "m1": m1, "m2": "0.00", "m3": m3, "base": base, "rate": "5", "tax": tax}


ROWS = [
    _row("111222333", "Ayala Land Inc.", "WC100", "Rentals", "10000.00", "10000.00", "20000.00", "1000.00"),
    _row("111222333", "Ayala Land Inc.", "WC158", "Supplier of goods", "5000.00", "0.00", "5000.00", "50.00"),
    _row("", "Pedro Cruz", "WI100", "Rentals", "0.00", "3000.00", "3000.00", "150.00"),
]


def test_one_certificate_per_payee_with_monthly_amounts():
    forms = payee_forms(ROWS, COMPANY, *Q3)
    assert [name for name, _ in forms] == ["Ayala Land Inc.", "Pedro Cruz"]
    ayala = forms[0][1]
    assert ayala.payee.tin == "11122233300000" and ayala.payor.tin == "12345678900000"
    assert (ayala.period_from, ayala.period_to) == ("07/01/2026", "09/30/2026")
    assert [(i.atc, i.m1, i.m3, i.total, i.tax_withheld) for i in ayala.ewt] == [
        ("WC100", 10000.0, 10000.0, 20000.0, 1000.0), ("WC158", 5000.0, 0.0, 5000.0, 50.0)]
    assert forms[1][1].payee.tin == ""


def test_more_atcs_than_rows_continue_on_another_copy():
    rows = [_row("111222333", "Ayala Land Inc.", f"WC{100 + i}", "Rentals", "1.00", "0.00", "1.00", "0.05")
            for i in range(12)]
    forms = payee_forms(rows, COMPANY, *Q3)
    assert [len(form.ewt) for _, form in forms] == [10, 2]


def test_zip_has_one_pdf_per_payee():
    with zipfile.ZipFile(io.BytesIO(build_zip(ROWS, COMPANY, *Q3))) as archive:
        names = archive.namelist()
        assert names == ["Ayala Land Inc. 2307.pdf", "Pedro Cruz 2307.pdf"]
        pdf = fitz.open("pdf", archive.read(names[0]))
        assert pdf.page_count == 1 and "WC100" in pdf[0].get_text()
