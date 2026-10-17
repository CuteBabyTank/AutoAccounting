"""Regression tests from the QBO 03 bank code review."""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

from app.services.accounting.books import bank

D = Decimal


class _Result:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None

    def scalar(self):
        return 0


class _CaptureDb:
    """An AsyncSession stand-in that records the SQL it is asked to run and returns nothing."""

    def __init__(self):
        self.sql: list[str] = []

    async def execute(self, stmt):
        self.sql.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return _Result()

    async def flush(self):
        return None


def _run(coro):
    return asyncio.run(coro)


def _only_live_statements(sql: str) -> bool:
    return "aa_documents.deleted_at IS NULL" in sql and "aa_documents.excluded" in sql


def test_lines_of_a_deleted_or_excluded_statement_document_do_not_post_or_block_the_close():
    company_id = uuid.uuid4()
    for call in (bank.matched_lines(_db := _CaptureDb(), company_id, date(2026, 12, 31)),
                 bank.unreconciled_accounts(_db2 := _CaptureDb(), company_id, date(2026, 12, 1), date(2026, 12, 31))):
        _run(call)
    assert _only_live_statements(_db.sql[0])
    assert _only_live_statements(_db2.sql[0])


def test_statements_of_a_deleted_document_are_not_the_first_statement():
    db = _CaptureDb()
    _run(bank._statements(db, uuid.uuid4(), "1020"))
    assert _only_live_statements(db.sql[0])


def test_a_transfer_between_own_bank_accounts_posts_once_when_both_statements_confirm_it():
    from app.services.accounting.compute.bank_books import MatchedLine, apply_bank_lines

    out = MatchedLine("a", date(2026, 12, 10), D("-5000.00"), "1020", "posting", "", D("5000.00"), "1021",
                      "Online transfer to 1021 acct 5566")
    into = MatchedLine("b", date(2026, 12, 11), D("5000.00"), "1021", "posting", "", D("5000.00"), "1020",
                       "Transfer from 0041-2288-7710")
    _, _, postings = apply_bank_lines([], (), [out, into])
    assert len(postings) == 1
    assert (postings[0].bank_account, postings[0].counter_account, postings[0].amount) == ("1020", "1021", D("-5000.00"))
    # two separate transfers of the same amount each keep their pair
    out2 = MatchedLine("c", date(2026, 12, 20), D("-5000.00"), "1020", "posting", "", D("5000.00"), "1021", "Transfer")
    _, _, postings = apply_bank_lines([], (), [out, into, out2])
    assert [p.id for p in postings] == ["a", "c"]


def test_confirming_an_invoice_its_linked_receipt_already_pays_moves_the_receipt_instead_of_paying_twice():
    from app.services.accounting.compute.bank_books import MatchedLine, apply_bank_lines
    from app.services.accounting.compute.books import Payment

    receipt = Payment("rcpt:r1", "inv1", date(2026, 12, 3), D("6720.00"), "cash", "OR-0659")
    line = MatchedLine("l1", date(2026, 12, 18), D("-6720.00"), "1020", "document", "inv1", D("6720.00"))
    payments, _, _ = apply_bank_lines([receipt], (), [line])
    assert len(payments) == 1
    assert (payments[0].id, payments[0].on, payments[0].via, payments[0].account) == (
        "rcpt:r1", date(2026, 12, 18), "bank", "1020")


def test_an_excluded_misread_or_duplicated_line_is_not_in_the_statement_balance():
    from app.services.accounting.compute.bank_reconcile import statement_balance

    lines = [(D("-100.00"), "matched"), (D("-100.00"), "excluded"), (D("50.00"), "unmatched")]
    assert statement_balance(D("1000.00"), lines) == D("950.00")
