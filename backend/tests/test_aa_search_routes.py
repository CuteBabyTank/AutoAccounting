"""Global search router: firm-scoped query builders, result items and grouping (no DB)."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.routers.accounting_search import (
    GROUP_TYPES, Filters, bank_line_item, bank_query, company_query, contact_item, contact_query, document_item,
    document_query, groups_for, journal_item, journal_query, rank, task_query,
)
from app.services.accounting.search import parse_query

TODAY = date(2026, 10, 18)
ENT = uuid.uuid4()
OTHER = uuid.uuid4()


def sql(stmt):
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def q(text):
    return parse_query(text, TODAY)


BUILDERS = (document_query, contact_query, bank_query, journal_query, task_query, company_query)


def test_every_builder_is_firm_scoped():
    for build in BUILDERS:
        text, params = sql(build(ENT, q("luzon"), Filters(), 20))
        assert "enterprise_id = " in text, build.__name__
        assert ENT in params.values(), build.__name__
        assert OTHER not in params.values()


def test_documents_skip_deleted_and_review_filter():
    text, _ = sql(document_query(ENT, q("luzon"), Filters(), 20))
    assert "aa_documents.deleted_at IS NULL" in text
    assert "aa_documents.reviewed IS false" not in text
    text, _ = sql(document_query(ENT, q("luzon"), Filters(review=True), 20))
    assert "aa_documents.needs_review IS true" in text and "aa_documents.reviewed IS false" in text
    assert "aa_documents.excluded IS false" in text


def test_document_amount_tin_date_reason_conditions():
    text, params = sql(document_query(ENT, q("1,500.00"), Filters(), 20))
    assert "aa_documents.gross_amount = " in text and Decimal("1500.00") in params.values()
    text, params = sql(document_query(ENT, q("123-456-789"), Filters(), 20))
    assert "aa_documents.seller_tin = " in text and "123456789" in params.values()
    text, params = sql(document_query(ENT, q("Oct 15, 2026"), Filters(), 20))
    assert "aa_documents.doc_date BETWEEN" in text and date(2026, 10, 15) in params.values()
    text, _ = sql(document_query(ENT, q("ewt expected"), Filters(), 20))
    assert "aa_documents.review_reasons @>" in text


def test_like_escape_is_used():
    text, params = sql(document_query(ENT, q("50%"), Filters(), 20))
    assert "ESCAPE" in text and "%50\\%%" in params.values()


def test_bank_amount_matches_both_signs_and_live_lines():
    text, params = sql(bank_query(ENT, q("₱1,500"), Filters(), 20))
    assert "aa_bank_lines.amount IN" in text
    flat = [v for p in params.values() for v in (p if isinstance(p, list) else [p])]
    assert Decimal("1500.00") in flat and Decimal("-1500.00") in flat
    assert "aa_bank_statements" in text and "deleted_at IS NULL" in text


def test_company_and_date_filters():
    cid = uuid.uuid4()
    text, params = sql(document_query(ENT, q("luzon"), Filters(company_id=cid, date_from=date(2026, 10, 1),
                                                               date_to=date(2026, 12, 31)), 20))
    assert cid in params.values() and "aa_documents.doc_date >=" in text and "aa_documents.doc_date <=" in text
    text, _ = sql(journal_query(ENT, q("rent"), Filters(date_from=date(2026, 10, 1)), 20))
    assert "aa_journal_entries.entry_date >=" in text and "aa_journal_entries.deleted_at IS NULL" in text


def test_groups_for_rules():
    assert groups_for(q("luzon"), Filters(), None) == list(GROUP_TYPES)
    assert groups_for(q("luzon"), Filters(), ["contact", "bogus"]) == ["contact"]
    dated = groups_for(q("luzon"), Filters(date_from=date(2026, 1, 1)), None)
    assert "contact" not in dated and "company" not in dated and "document" in dated
    assert groups_for(q("luzon"), Filters(review=True), None) == ["document"]
    assert groups_for(q(""), Filters(review=True), None) == ["document"]
    assert groups_for(q(""), Filters(), None) == []
    assert groups_for(q("a"), Filters(), None) == []


def doc(**kw):
    values = dict(id=uuid.uuid4(), company_id=uuid.uuid4(), client_role="buyer", doc_number="5838",
                  seller_name="Luzon Paint Center", seller_tin="123456789", buyer_name="Bayanihan Hardware",
                  buyer_tin="400500600", document_title="Sales Invoice", doc_type="invoice", category="purchases",
                  doc_date=date(2026, 12, 3), gross_amount=Decimal("1500.00"), vatable_amount=Decimal("1339.29"),
                  vat_amount=Decimal("160.71"), withholding_amount=Decimal("0"), period_year=2026, period_quarter=4,
                  page_start=3, needs_review=True, reviewed=False, excluded=False,
                  review_reasons=["possible_duplicate"], payment_ref="")
    values.update(kw)
    return SimpleNamespace(**values)


def test_document_item_context_and_matches():
    d = doc()
    item = document_item(d, "Bayanihan Hardware", q("1500"))
    assert item["type"] == "document" and item["document_id"] == str(d.id) and item["page"] == 3
    assert item["subtitle"].startswith("Luzon Paint Center")
    assert (item["period_year"], item["period_quarter"]) == (2026, 4)
    assert "amount" in item["matched"] and item["amount"] == "1500.00"
    sale = document_item(doc(client_role="seller", buyer_name="Kalayaan Construction"), "X", q("kalayaan"))
    assert sale["subtitle"].startswith("Kalayaan Construction") and "name" in sale["matched"]
    assert "tin" in document_item(d, "X", q("123 456 789 000"))["matched"]
    assert "number" in document_item(d, "X", q("5838"))["matched"]
    assert "reason" in document_item(d, "X", q("duplicate"))["matched"]
    assert "date" in document_item(d, "X", q("12/03/2026"))["matched"]


def test_rank_puts_exact_number_first_and_cuts():
    items = [document_item(doc(doc_number=n), "X", q("5838")) for n in ("SI-15838", "5838", "5838-A")]
    ranked = rank(items, 2)
    assert [i["title"].split(" ")[-1] for i in ranked[0]] == ["5838", "5838-A"]
    assert ranked[1] is True


def test_bank_contact_journal_items():
    line = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), account_code="1020", line_date=date(2026, 12, 9),
                           amount=Decimal("-1500.00"), narration="CHK 0012 STA ELENA REALTY", check_no="0012",
                           match_status="matched")
    item = bank_line_item(line, uuid.uuid4(), "Co", 12, q("1500"))
    assert (item["account_code"], item["month"], item["fiscal_year"]) == ("1020", "2026-12", 2026)
    assert "amount" in item["matched"] and item["amount"] == "-1500.00"
    june = bank_line_item(SimpleNamespace(**{**vars(line), "line_date": date(2026, 7, 2)}), uuid.uuid4(), "Co", 6,
                          q("elena"))
    assert june["fiscal_year"] == 2027
    c = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), registered_name="Luzon Paint Center",
                        tin="123456789", role="supplier", aliases=["LUZON PAINT"])
    ci = contact_item(c, "Co", q("123456789"))
    assert ci["role"] == "supplier" and "tin" in ci["matched"] and ci["tin"] == "123456789"
    je = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), entry_date=date(2026, 12, 31), reference="AJE-3",
                         particulars="Accrue December rent", kind="manual", book="GJ", is_adjusting=True)
    ji = journal_item(je, "Co", 12, q("rent"))
    assert ji["fiscal_year"] == 2026 and ji["reference"] == "AJE-3" and ji["title"].startswith("AJE-3")
