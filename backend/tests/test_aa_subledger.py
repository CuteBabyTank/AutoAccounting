"""A/R and A/P open items, aging and 2307 items (pure), with the Q4 pack as the acceptance fixture.

Per-document detail comes from the CSVs imported into QBO (docs/superpowers/research/2026-10-16-qbo-q4-run/):
03_invoices_fixed / 04_sales_receipts / 04b_credit_note for sales, 05_bills_import (+ the hand-entered Sta. Elena rent
bill) for purchases, 06-08 feeds for how each was paid.
"""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.subledger import (
    BUCKETS, OpenDoc, Received2307, aging, aging_totals, bucket, counter_paid, cwt_items, due_date_for, open_items,
)

D = Decimal
AS_OF = date(2026, 12, 31)


def _d(text: str) -> date:
    m, d, y = text.split("/")
    return date(int(y), int(m), int(d))


def doc(id, kind, name, on, total, *, withheld="0", counter=False, due=None, terms_days=None, unverified=False,
        period=(2026, 4)):
    return OpenDoc(id=id, kind=kind, contact_key=f"NAME:{name.lower()}", contact_name=name, contact_tin="",
                   doc_number=id, doc_date=on, total=D(total), withheld=D(withheld), paid_at_counter=counter,
                   due_date=due, terms_days=terms_days, payment_unverified=unverified, period=period)


# (number, supplier, date, printed due, terms, total) — 05_bills_import.csv summed per bill
BILLS = [
    ("88548", "Pacific Steel & Cement Supply Inc.", "10/01/2026", "10/31/2026", "Net 30", "160227.20"),
    ("5838", "Luzon Paint Distributors Corp.", "11/05/2026", "11/20/2026", "Net 15", "70089.60"),
    ("10759", "Techworld Computer Center Inc.", "11/12/2026", "11/12/2026", "Due on receipt", "84000.00"),
    ("EB-7781-2525", "Metro Luzon Electric Company", "11/15/2026", "11/25/2026", "", "9464.00"),
    ("RS-1048", "Reyes Santos & Co., CPAs", "10/31/2026", "11/15/2026", "Net 15", "28000.00"),
    ("001190", "Kusina ni Lola Restaurant", "11/28/2026", "11/28/2026", "Due on receipt", "4704.00"),
    ("PB-44437", "Petro Bayan Gas Station", "12/04/2026", "12/04/2026", "bank", "3500.00"),
    ("0538", "Aling Nena's School & Office Supplies", "10/22/2026", "10/22/2026", "Due on receipt", "1650.00"),
    ("OR-0659", "QuickFix Aircon Services", "12/18/2026", "12/18/2026", "bank", "6720.00"),
    ("8098", "Golden Hardware Wholesale", "12/25/2026", "12/25/2026", "bank", "22600.00"),
    ("OR-7781904", "City Government of Marikina", "11/03/2026", "11/03/2026", "Due on receipt", "3500.00"),
    ("C-2026-1119-44812", "Guangzhou Hengli Tools Mfg. Co., Ltd.", "11/19/2026", "11/19/2026", "", "176400.00"),
    ("BOC-0198832", "Bureau of Customs", "11/19/2026", "11/19/2026", "Due on receipt", "32770.00"),
    ("C-44812-FRT", "R. Villanueva (Customs Broker)", "11/19/2026", "11/19/2026", "", "10350.00"),
    ("0048029", "Tindahan Mart Supermarket", "10/06/2026", "10/06/2026", "Due on receipt", "2992.25"),
    ("221401235", "Sulit-Stop Convenience Store", "10/09/2026", "10/09/2026", "Due on receipt", "554.00"),
    ("0012151", "Botika ng Bayan Pharmacy", "10/14/2026", "10/14/2026", "Due on receipt", "1970.00"),
    ("087-0034439", "Pahina Bookstore", "10/20/2026", "10/20/2026", "Due on receipt", "6326.25"),
    ("CK-019150", "Kape Kanto Coffee", "10/24/2026", "10/24/2026", "Due on receipt", "1445.00"),
    ("0128-0442219", "Manok House Fast Food", "10/31/2026", "10/31/2026", "Due on receipt", "4319.00"),
    ("SG-2026-11-0091564", "SakayGo Technologies Inc.", "11/02/2026", "11/02/2026", "Due on receipt", "426.00"),
    ("PG-034728", "Park-N-Go Parking", "11/02/2026", "11/02/2026", "Due on receipt", "150.00"),
    ("0052607", "Tindahan Mart Supermarket", "11/03/2026", "11/03/2026", "Due on receipt", "3101.75"),
    ("PB-45304", "Petro Bayan Gas Station", "11/09/2026", "11/09/2026", "Due on receipt", "3049.48"),
    ("T3-88121248", "Metro Expressway Toll Corp.", "11/09/2026", "11/09/2026", "Due on receipt", "302.00"),
    ("PX-0045-77440", "Padala Express Courier", "11/11/2026", "11/11/2026", "Due on receipt", "1360.00"),
    ("0729", "Kidlat Printing & Xerox", "11/14/2026", "11/14/2026", "Due on receipt", "2076.50"),
    ("1504", "Aqua Pure Water Refilling Station", "11/18/2026", "11/18/2026", "Due on receipt", "270.00"),
    ("CH-0991361", "Citimart Hardware & Home", "11/21/2026", "11/21/2026", "Due on receipt", "4754.00"),
    ("064-0083664", "Mega Department Store", "11/25/2026", "11/25/2026", "Due on receipt", "6045.75"),
    ("CH-1129870", "Citimart Hardware & Home", "11/28/2026", "11/28/2026", "Due on receipt", "5750.00"),
    ("KG-01079", "Kaldero Grill & Restaurant", "12/05/2026", "12/05/2026", "Due on receipt", "2746.50"),
    ("PX-0045-91220", "Padala Express Courier", "12/10/2026", "12/10/2026", "Due on receipt", "3510.00"),
    ("0061504", "Tindahan Mart Supermarket", "12/12/2026", "12/12/2026", "Due on receipt", "2353.00"),
    ("0071420", "Tindahan Mart Supermarket", "12/14/2026", "12/14/2026", "Due on receipt", "25992.00"),
    ("PB-45919", "Petro Bayan Gas Station", "12/19/2026", "12/19/2026", "Due on receipt", "3698.14"),
    ("HC-1219", "Handaan Catering Services Inc.", "12/19/2026", "12/19/2026", "", "38640.00"),
    ("221402050", "Sulit-Stop Convenience Store", "12/22/2026", "12/22/2026", "Due on receipt", "1515.00"),
    ("KG-01188", "Kaldero Grill & Restaurant", "12/22/2026", "12/22/2026", "Due on receipt", "2670.00"),
    ("CH-1004838", "Citimart Hardware & Home", "12/27/2026", "12/27/2026", "Due on receipt", "1414.00"),
    ("ACK-20261229", "Mang Tomas Sari-Sari Store", "12/29/2026", "12/29/2026", "Due on receipt", "680.00"),
    ("89904", "Pacific Steel & Cement Supply Inc.", "12/02/2026", "01/01/2027", "Net 30", "263872.00"),
]
# 08_feed_bank_dec.csv: lines matched to bills
BANK = {"PB-44437": ("12/04/2026", "3500.00"), "OR-0659": ("12/18/2026", "6720.00"),
        "8098": ("12/25/2026", "22600.00"), "SE-RENT-12": ("12/02/2026", "32100.00")}


def q4_bills() -> tuple[list[OpenDoc], list[Payment]]:
    docs, payments = [], []
    for number, name, on, due, terms, total in BILLS:
        printed = _d(due) if due != on else None
        days = {"Net 30": 30, "Net 15": 15}.get(terms)
        docs.append(doc(number, "ap", name, _d(on), total, counter=terms == "Due on receipt",
                        due=printed if days is None else None, terms_days=days,
                        unverified=terms.startswith("Net")))
    # Sta. Elena Realty December rent: ₱30,000 + ₱3,600 VAT, 5% EWT ₱1,500 withheld, paid by check #000818
    docs.append(doc("SE-RENT-12", "ap", "Sta. Elena Realty", date(2026, 12, 1), "33600.00", withheld="1500.00"))
    for number, (on, amount) in BANK.items():
        payments.append(Payment(f"bank:{number}", number, _d(on), D(amount), "bank", ""))
    return docs, payments


def q4_sales() -> tuple[list[OpenDoc], list[Payment]]:
    docs = [
        doc("0005", "ar", "Mabuhay Builders Inc.", date(2026, 10, 3), "118004.32", terms_days=30),
        doc("0006", "ar", "Kalayaan Construction Co.", date(2026, 10, 18), "270558.40", withheld="2415.70",
            terms_days=30),
        doc("0007", "ar", "Juan Dela Cruz", date(2026, 11, 22), "21616.00", counter=True),
        doc("0008", "ar", "Mabuhay Builders Inc.", date(2026, 12, 10), "131476.80", terms_days=30),
        doc("0009", "ar", "San Roque Parish Church", date(2026, 12, 20), "42224.00", counter=True),
    ]
    payments = [Payment("bank:mabuhay", "0008", date(2026, 12, 11), D("50000.00"), "bank", "")]
    return docs, payments


def test_q4_ar_total_and_buckets():
    docs, payments = q4_sales()
    items = open_items(docs, payments, AS_OF, {})
    assert sorted(i.doc.id for i in items) == ["0005", "0006", "0008"]
    assert sum(i.open for i in items) == D("467623.82")
    by_id = {i.doc.id: i for i in items}
    assert by_id["0006"].open == D("268142.70")
    assert by_id["0008"].open == D("81476.80") and by_id["0008"].due == date(2027, 1, 9)
    totals = aging_totals(aging(items))
    assert totals == {"current": D("81476.80"), "1-30": D("0.00"), "31-60": D("386147.02"), "61-90": D("0.00"),
                      "90+": D("0.00"), "total": D("467623.82")}


def test_q4_ap_total_and_buckets():
    docs, payments = q4_bills()
    items = open_items(docs, payments, AS_OF, {})
    assert len(items) == 8
    assert sum(i.open for i in items) == D("757042.80")
    totals = aging_totals(aging(items))
    assert totals == {"current": D("263872.00"), "1-30": D("38640.00"), "31-60": D("294303.60"),
                      "61-90": D("160227.20"), "90+": D("0.00"), "total": D("757042.80")}
    rows = {r.name: r for r in aging(items)}
    assert rows["Pacific Steel & Cement Supply Inc."].count == 2
    assert rows["Pacific Steel & Cement Supply Inc."].total == D("424099.20")
    assert all(i.doc.payment_unverified for i in items if i.doc.id in ("88548", "89904", "5838", "RS-1048"))


def test_cash_receipt_is_not_open():
    items = open_items([doc("1", "ap", "Tindahan", date(2026, 10, 6), "2992.25", counter=True)], [], AS_OF, {})
    assert items == []


def test_unclear_terms_stay_open():
    items = open_items([doc("1", "ap", "Handaan", date(2026, 12, 19), "38640.00")], [], AS_OF, {})
    assert [(i.open, i.bucket) for i in items] == [(D("38640.00"), "1-30")]


def test_payment_after_as_of_ignored():
    d = doc("1", "ar", "Mabuhay", date(2026, 12, 10), "1000.00")
    pay = [Payment("p", "1", date(2027, 1, 5), D("400.00"), "bank", "")]
    assert open_items([d], pay, AS_OF, {})[0].open == D("1000.00")
    assert open_items([d], pay, date(2027, 1, 31), {})[0].open == D("600.00")
    assert open_items([d], [Payment("p", "1", date(2026, 12, 20), None, "cash", "")], AS_OF, {}) == []


def test_document_after_as_of_left_out():
    assert open_items([doc("1", "ar", "M", date(2027, 1, 2), "10.00")], [], AS_OF, {}) == []


def test_credit_memo_negative_item():
    items = open_items([doc("1", "ar", "Mabuhay", date(2026, 12, 1), "-500.00")], [], AS_OF, {})
    assert [(i.open, i.bucket) for i in items] == [(D("-500.00"), "1-30")]


def test_due_date_priority():
    on = date(2026, 10, 1)
    assert due_date_for(doc("1", "ap", "X", on, "1", due=date(2026, 10, 9), terms_days=30), 45) == date(2026, 10, 9)
    assert due_date_for(doc("1", "ap", "X", on, "1", terms_days=30), 45) == date(2026, 10, 31)
    assert due_date_for(doc("1", "ap", "X", on, "1"), 45) == date(2026, 11, 15)
    assert due_date_for(doc("1", "ap", "X", on, "1"), None) == on


def test_contact_terms_used_for_due_date():
    items = open_items([doc("1", "ap", "X", date(2026, 12, 1), "100")], [], AS_OF, {"NAME:x": 30})
    assert items[0].due == date(2026, 12, 31) and items[0].bucket == "current"


def test_bucket_edges():
    assert [bucket(n) for n in (-5, 0, 1, 30, 31, 60, 61, 90, 91)] == [
        "current", "current", "1-30", "1-30", "31-60", "31-60", "61-90", "61-90", "90+"]
    assert BUCKETS == ("current", "1-30", "31-60", "61-90", "90+")


def test_counter_paid():
    assert counter_paid("cash", D("0"))
    assert counter_paid("", D("2000"))
    assert not counter_paid("credit", D("0"))
    assert not counter_paid("", D("0"))


def test_kalayaan_cwt_pending_then_received():
    docs, _ = q4_sales()
    pending = cwt_items(docs, {}, [])
    assert [(c.doc_id, c.amount, c.status) for c in pending] == [("0006", D("2415.70"), "pending")]
    key = docs[1].contact_key
    received = cwt_items(docs, {}, [Received2307("cert", key, (2026, 4), D("2415.70"))])
    assert (received[0].status, received[0].document_id, received[0].source) == ("received", "cert", "auto")
    other_quarter = cwt_items(docs, {}, [Received2307("cert", key, (2026, 3), D("2415.70"))])
    assert other_quarter[0].status == "pending"


def test_user_mark_wins():
    docs, _ = q4_sales()
    key = docs[1].contact_key
    items = cwt_items(docs, {"0006": {"status": "pending"}}, [Received2307("cert", key, (2026, 4), D("2415.70"))])
    assert (items[0].status, items[0].source) == ("pending", "user")
    items = cwt_items(docs, {"0006": {"status": "received", "document_id": "x"}}, [])
    assert (items[0].status, items[0].document_id, items[0].source) == ("received", "x", "user")


def test_control_tie_explains_books_vs_aging():
    """The books keep customer CWT in A/R until the 2307 posts and leave counter-paid documents in A/R / A/P until a
    payment is recorded; the aging nets both. The tie lists each difference so aging + lines = the GL control."""
    from app.services.accounting.compute.subledger import control_tie

    start = date(2026, 10, 1)
    docs = [doc("SI-1", "ar", "Kalayaan", date(2026, 10, 5), "11200.00", withheld="200.00"),
            doc("SI-2", "ar", "Walk-in", date(2026, 11, 2), "560.00", counter=True),
            doc("SI-3", "ar", "Mabuhay", date(2026, 11, 9), "5600.00", withheld="100.00"),
            doc("OLD", "ar", "Old", date(2026, 9, 1), "1000.00", withheld="50.00"),     # before the books start
            doc("BL-1", "ap", "Pacific", date(2026, 10, 7), "8000.00", withheld="80.00"),
            doc("OR-9", "ap", "Hardware", date(2026, 12, 1), "1120.00", withheld="0", counter=True)]
    pays = [Payment("p1", "SI-1", date(2026, 11, 30), None, "bank", "")]
    items = open_items(docs, pays, AS_OF, {})
    ar_total = sum((i.open for i in items if i.doc.kind == "ar"), D("0"))
    assert ar_total == D("6450.00")                       # SI-3 5,500 + OLD 950
    # books A/R: SI-1 200 CWT left, SI-2 560 (no payment), SI-3 5,600, minus a 2307 for SI-1 (200) booked → 6,160;
    # plus an opening balance of 1,000 for OLD
    ar = control_tie("ar", docs, pays, AS_OF, start, ar_total, D("7160.00"), D("200.00"))
    assert [(l.key, l.amount) for l in ar] == [
        ("aging", D("6450.00")), ("cwt", D("100.00")), ("counter", D("560.00")), ("other", D("50.00")),
        ("books", D("7160.00"))]
    assert sum((l.amount for l in ar[1:-1]), ar[0].amount) == ar[-1].amount

    ap_total = sum((i.open for i in items if i.doc.kind == "ap"), D("0"))
    ap = control_tie("ap", docs, pays, AS_OF, start, ap_total, D("9040.00"), D("0"))
    assert [(l.key, l.amount) for l in ap] == [("aging", D("7920.00")), ("counter", D("1120.00")),
                                               ("books", D("9040.00"))]
    # all tied: just aging and books, the same figure
    assert [l.key for l in control_tie("ap", docs[4:5], [], AS_OF, start, D("7920.00"), D("7920.00"), D("0"))] == [
        "aging", "books"]
