"""Customer statement activity: balance forward and transaction statements (pure), and the PDF for each type."""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.subledger import payment_rows
from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.statement import activity
from app.services.accounting.compute.subledger import OpenDoc, open_items

D = Decimal


def doc(i, total, on, withheld="0", counter=False):
    return OpenDoc(id=i, kind="ar", contact_key="k", contact_name="Kalayaan", contact_tin="400500600",
                   doc_number=i, doc_date=on, total=D(total), withheld=D(withheld), paid_at_counter=counter)


DOCS = [doc("0001", "11200.00", date(2026, 9, 10), withheld="200.00"),
        doc("0006", "270558.40", date(2026, 10, 18), withheld="2415.70"),
        doc("CM1", "-1000.00", date(2026, 10, 25)),
        doc("POS", "500.00", date(2026, 10, 26), counter=True)]
PAYS = [Payment("bank:1", "0001", date(2026, 10, 2), None, "bank", "DEP 123"),
        Payment("rcpt:2", "0006", date(2026, 11, 5), D("100000.00"), "cash", "OR 77"),
        Payment("wo:je:0006", "0006", date(2026, 12, 1), D("5000.00"), "writeoff", "Write-off")]


def run(start, end):
    return activity(DOCS, payment_rows(DOCS, PAYS), start, end)


def test_balance_forward_opening_and_window_lines():
    out = run(date(2026, 10, 1), date(2026, 10, 31))
    assert out["opening"] == D("11000.00")
    assert [(l["date"], l["kind"], l["number"], l["charge"], l["credit"]) for l in out["lines"]] == [
        (date(2026, 10, 2), "payment", "0001", D("0.00"), D("11000.00")),
        (date(2026, 10, 18), "invoice", "0006", D("268142.70"), D("0.00")),
        (date(2026, 10, 25), "credit", "CM1", D("0.00"), D("1000.00")),
    ]
    assert [l["balance"] for l in out["lines"]] == [D("0.00"), D("268142.70"), D("267142.70")]
    assert out["closing"] == D("267142.70")


def test_closing_ties_to_the_open_items():
    for end in (date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31)):
        out = run(date(2026, 9, 1), end)
        assert out["closing"] == sum((i.open for i in open_items(DOCS, PAYS, end, {})), D("0"))
    assert run(date(2026, 12, 1), date(2026, 12, 31))["lines"][0]["kind"] == "writeoff"


def test_counter_paid_sales_stay_off():
    assert all(l["number"] != "POS" for l in run(date(2026, 1, 1), date(2026, 12, 31))["lines"])


def test_statement_pdfs_render_for_each_type():
    from app.services.accounting.books_pdf import Header
    from app.services.accounting.subledger_report import statement_pdf
    header = Header("Bayanihan Hardware", "123-456-789-000", "Marikina")
    items = open_items(DOCS, PAYS, date(2026, 10, 31), {})
    act = run(date(2026, 10, 1), date(2026, 10, 31))
    for kind in ("open_item", "balance_forward", "transaction"):
        pdf = statement_pdf(header, {"name": "Kalayaan", "tin": "", "address": ""}, date(2026, 10, 31), items,
                            D("2415.70"), kind=kind, start=date(2026, 10, 1), activity=act)
        assert pdf.startswith(b"%PDF")
