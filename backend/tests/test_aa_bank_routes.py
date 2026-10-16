from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.accounting_bank import ConfirmLineIn
from app.schemas.accounting_books import AccountPatch, CloseMonthIn
from app.services.accounting.books.closing import BANK_BLOCK, bank_block_message


def test_close_blocks_on_unreconciled_statement_month():
    message = bank_block_message(["1020"], date(2026, 12, 1), "")
    assert message.startswith(BANK_BLOCK) and "1020" in message and "December 2026" in message
    assert bank_block_message(["1020"], date(2026, 12, 1), "  ok ") is not None   # too short to count as a reason
    assert bank_block_message(["1020"], date(2026, 12, 1), "Statement arrives late; CPA approved") is None
    assert bank_block_message([], date(2026, 12, 1), "") is None


def test_close_accepts_an_override_reason_and_accounts_a_bank_number():
    assert CloseMonthIn(month_start=date(2026, 12, 1)).override_reason == ""
    assert AccountPatch(bank_account_no="0041-2288-7710").bank_account_no == "0041-2288-7710"


def test_confirm_line_body_is_strict():
    assert ConfirmLineIn().kind is None
    with pytest.raises(ValidationError):
        ConfirmLineIn(kind="anything")
    with pytest.raises(ValidationError):
        ConfirmLineIn(amount=0)
    with pytest.raises(ValidationError):
        ConfirmLineIn(surprise=1)


def test_bank_routes_are_registered():
    from app.routers import accounting, accounting_bank

    import inspect

    assert "router.include_router(accounting_bank.router)" in inspect.getsource(accounting)
    paths = {getattr(r, "path", "") for r in accounting_bank.router.routes}
    assert {"/companies/{company_id}/bank", "/companies/{company_id}/bank/lines", "/bank-lines/{line_id}/confirm",
            "/bank-lines/{line_id}/reject", "/bank-lines/{line_id}/exclude", "/companies/{company_id}/bank/reconcile",
            "/bank-statements/{statement_id}", "/bank-reconciliations/{rec_id}/file"} <= paths
