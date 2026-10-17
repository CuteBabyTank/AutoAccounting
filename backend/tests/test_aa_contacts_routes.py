"""Subledger glue: documents → contacts / open docs, contact list rows, payments per document (pure parts)."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.books.subledger import (
    Subledger, doc_kind, key_map_for, open_doc_from, payment_rows, seen_party,
)
from app.routers.accounting_contacts import aging_out, contact_rows
from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.subledger import CwtItem, open_items

D = Decimal


def document(**kw):
    values = dict(id=uuid.uuid4(), category="sales", client_role="seller", settles_document_id=None, deleted_at=None,
                  excluded=False, doc_date=date(2026, 10, 18), doc_number="0006", buyer_tin="400500600",
                  buyer_name="Kalayaan Construction Co.", buyer_address="Marikina", seller_tin="", seller_name="",
                  seller_address="", seller_vat_registered=None, gross_amount=D("270558.40"),
                  withholding_amount=D("2415.70"), paid_on=None, raw={"payment_terms": "credit", "terms_days": 30},
                  review_reasons=[], cwt_2307={}, period_year=2026, period_quarter=4)
    values.update(kw)
    return SimpleNamespace(**values)


def contact(key, name, tin="", role="customer", merged=None, cid=None):
    return SimpleNamespace(id=cid or uuid.uuid4(), key=key, registered_name=name, tin=tin, role=role, aliases=[],
                           merged_into_id=merged, payment_terms_days=None)


def test_doc_kind():
    assert doc_kind(document()) == "ar"
    assert doc_kind(document(category="expenses", client_role="buyer")) == "ap"
    assert doc_kind(document(category="payroll", client_role="buyer")) is None
    assert doc_kind(document(settles_document_id=uuid.uuid4())) is None


def test_open_doc_from_sale_nets_cwt_and_reads_terms():
    d = document()
    o = open_doc_from(d, {}, {}, {}, 12)
    assert (o.kind, o.contact_key, o.withheld, o.terms_days, o.period, o.paid_at_counter) == (
        "ar", "400500600", D("2415.70"), 30, (2026, 4), False)


def test_open_doc_from_bill_uses_computed_ewt_and_counter():
    d = document(category="expenses", client_role="buyer", seller_tin="111222333", seller_name="Sta. Elena Realty",
                 buyer_tin="", buyer_name="", withholding_amount=D("0"), raw={"payment_terms": "", "cash_tendered": 0})
    o = open_doc_from(d, {str(d.id): D("1500.00")}, {}, {}, 12)
    assert o.withheld == D("1500.00") and not o.paid_at_counter
    pos = document(category="expenses", client_role="buyer", seller_name="Tindahan", buyer_name="",
                   buyer_tin="", raw={"cash_tendered": "2000.00"})
    assert open_doc_from(pos, {}, {}, {}, 12).paid_at_counter
    # paid_on wins over the counter guess: the payment itself is the evidence
    assert not open_doc_from(document(paid_on=date(2026, 10, 18), raw={"payment_terms": "cash"}), {}, {}, {},
                             12).paid_at_counter


def test_open_doc_from_follows_merge_and_shows_target_name():
    d = document(buyer_tin="", buyer_name="Kalayaan Constr")
    o = open_doc_from(d, {}, {"NAME:kalayaan constr": "400500600"}, {"400500600": ("Kalayaan Construction Co.",
                                                                                   "400500600")}, 12)
    assert (o.contact_key, o.contact_name, o.contact_tin) == ("400500600", "Kalayaan Construction Co.", "400500600")


def test_seen_party_roles_and_skips():
    assert seen_party(document()).role == "customer"
    s = seen_party(document(category="purchases", client_role="buyer", seller_tin="111222333", seller_name="Luzon",
                            seller_vat_registered=True))
    assert (s.role, s.key, s.vat) == ("supplier", "111222333", True)
    assert seen_party(document(category="payroll")) is None
    assert seen_party(document(excluded=True)) is None
    assert seen_party(document(buyer_tin="", buyer_name="  ")) is None


def test_key_map_follows_merges():
    target = contact("400500600", "Kalayaan")
    source = contact("NAME:kalayaan constr", "Kalayaan Constr", merged=target.id)
    assert key_map_for([target, source]) == {"400500600": "400500600", "NAME:kalayaan constr": "400500600"}


def test_payment_rows_resolve_full_payments():
    o = open_doc_from(document(withholding_amount=D("0"), gross_amount=D("1000.00")), {}, {}, {}, 12)
    rows = payment_rows([o], [Payment("bank:1", o.id, date(2026, 11, 1), D("400.00"), "bank", ""),
                              Payment("paid:x", o.id, date(2026, 11, 5), None, "cash", ""),
                              Payment("bank:2", "other", date(2026, 11, 5), D("5"), "bank", "")])
    assert [(p.id, a) for p, a in rows] == [("bank:1", D("400.00")), ("paid:x", D("600.00"))]


def _sub(docs, contacts, payments=(), cwt=()):
    opens = [open_doc_from(d, {}, key_map_for(contacts), {c.key: (c.registered_name, c.tin) for c in contacts}, 12)
             for d in docs]
    as_of = date(2026, 12, 31)
    return Subledger(as_of, contacts, opens, open_items(opens, list(payments), as_of, {}), list(cwt), list(payments),
                     {}, [], {str(d.id): d for d in docs})


def test_contact_rows_balance_overdue_and_cwt():
    k = contact("400500600", "Kalayaan Construction Co.", "400500600")
    m = contact("300400500", "Mabuhay Builders Inc.", "300400500", role="both")
    s = contact("111222333", "Luzon Paint", "111222333", role="supplier")
    d6 = document()
    d8 = document(doc_number="0008", buyer_tin="300400500", buyer_name="Mabuhay Builders Inc.",
                  doc_date=date(2026, 12, 10), gross_amount=D("131476.80"), withholding_amount=D("0"))
    sub = _sub([d6, d8], [k, m, s], [Payment("bank:m", str(d8.id), date(2026, 12, 11), D("50000"), "bank", "")],
               [CwtItem(str(d6.id), "400500600", D("2415.70"), (2026, 4), "pending", None, "")])
    rows = {r.registered_name: r for r in contact_rows(sub, "customer")}
    assert set(rows) == {"Kalayaan Construction Co.", "Mabuhay Builders Inc."}
    assert rows["Kalayaan Construction Co."].open_balance == D("268142.70")
    assert rows["Kalayaan Construction Co."].overdue == D("268142.70")
    assert rows["Kalayaan Construction Co."].cwt_pending == D("2415.70")
    assert rows["Mabuhay Builders Inc."].open_balance == D("81476.80")
    assert rows["Mabuhay Builders Inc."].overdue == D("0.00")
    assert [r.registered_name for r in contact_rows(sub, "supplier")] == ["Luzon Paint", "Mabuhay Builders Inc."]
    out = aging_out(sub, "ar")
    assert out.totals["total"] == D("349619.50") and len(out.rows) == 2


def test_merged_contacts_are_not_listed():
    target = contact("400500600", "Kalayaan")
    source = contact("NAME:kalayaan constr", "Kalayaan Constr", merged=target.id)
    sub = _sub([document()], [target, source])
    assert [r.registered_name for r in contact_rows(sub, "customer")] == ["Kalayaan"]


class _FakeDb:
    """Records statements; every SELECT finds no contacts (a first page load on a company)."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def flush(self):
        pass


def test_sync_contacts_insert_tolerates_a_concurrent_sync():
    """The contacts list and the aging load together and both sync: a party the other request just inserted must be
    skipped (ON CONFLICT DO NOTHING), not fail the page on the unique key."""
    import asyncio

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.dml import Insert

    from app.services.accounting.books.subledger import sync_contacts

    db = _FakeDb()
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4())
    asyncio.run(sync_contacts(db, company, [document(), document(buyer_tin="400500601", buyer_name="Mabuhay")]))
    inserts = [s for s in db.statements if isinstance(s, Insert)]
    assert len(inserts) == 1
    sql = str(inserts[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_aa_contact_key DO NOTHING" in sql



def test_placeholder_tin_does_not_merge_unrelated_customers():
    """Walk-in invoices print TIN 000-000-000-000: two different buyers must not become one contact."""
    from app.services.accounting.contacts import plan_contacts

    a = document(buyer_tin="000000000", buyer_name="Juan Dela Cruz")
    b = document(buyer_tin="000000000", buyer_name="Maria Santos Trading")
    seen = [seen_party(a), seen_party(b)]
    assert seen[0].key != seen[1].key and seen[0].tin == ""
    creates, _ = plan_contacts(seen, [])
    assert sorted(c["registered_name"] for c in creates) == ["Juan Dela Cruz", "Maria Santos Trading"]
    assert open_doc_from(a, {}, {}, {}, 12).contact_key == seen[0].key
