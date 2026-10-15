"""Validation tests for the form filler service."""
from app.schemas.form_filler import FilledForm, LineItem, Payee, Payor
from app.services.form_filler_service import (
    PAYEE_KIND, PAYOR_KIND, ParseResult, validate,
)


def _payee(**kw) -> Payee:
    base = dict(tin="123-456-789-000", name="Acme",
                registered_address="Addr", zip_code="1226", foreign_address="")
    base.update(kw)
    return Payee(**base)


def _payor(**kw) -> Payor:
    base = dict(tin="999-888-777-000", name="ABC",
                registered_address="1 Main", zip_code="1000")
    base.update(kw)
    return Payor(**base)


def _form(payee: Payee, payor: Payor, **kw) -> FilledForm:
    base = dict(excel_row=7, payee=payee, payor=payor,
                period_from="01/01/2026", period_to="03/31/2026",
                ewt=[LineItem(description="X", atc="WI010",
                              m1=100, m2=200, m3=300, total=600, tax_withheld=30)],
                money_payments=[])
    base.update(kw)
    return FilledForm(**base)


def _payee_result(payee: Payee | None = None, payor: Payor | None = None,
                  period_from="01/01/2026", period_to="03/31/2026",
                  forms=None) -> ParseResult:
    payee = payee or _payee()
    payor = payor or _payor()
    forms = forms if forms is not None else [_form(payee, payor)]
    return ParseResult(kind=PAYEE_KIND, period_from=period_from, period_to=period_to,
                       payee=payee, payor=None, forms=forms)


def _payor_result(payor: Payor | None = None, payee: Payee | None = None,
                  forms=None) -> ParseResult:
    payor = payor or _payor()
    payee = payee or _payee()
    forms = forms if forms is not None else [_form(payee, payor)]
    return ParseResult(kind=PAYOR_KIND, period_from="01/01/2026", period_to="03/31/2026",
                       payee=None, payor=payor, forms=forms)


def test_valid_payee_form_yields_no_errors() -> None:
    assert validate(_payee_result()) == []


def test_valid_payor_form_yields_no_errors() -> None:
    assert validate(_payor_result()) == []


def test_bad_payee_tin_flagged() -> None:
    errs = validate(_payee_result(payee=_payee(tin="abc")))
    codes = {(e.sheet, e.column, e.code) for e in errs}
    assert ("PayeeForm", "payee_tin", "TIN_FORMAT") in codes


def test_payor_form_validates_constant_payor() -> None:
    errs = validate(_payor_result(payor=_payor(tin="abc")))
    assert any(e.sheet == "PayorForm" and e.column == "payor_tin"
               and e.code == "TIN_FORMAT" for e in errs)


def test_missing_name_flagged_required() -> None:
    errs = validate(_payee_result(payee=_payee(name="")))
    assert any(e.code == "REQUIRED" and e.column == "payee_name" for e in errs)


def test_zip_format_flagged() -> None:
    errs = validate(_payee_result(payee=_payee(zip_code="12")))
    assert any(e.code == "ZIP_FORMAT" for e in errs)


def test_date_range_flagged() -> None:
    errs = validate(_payee_result(period_from="04/01/2026", period_to="01/01/2026"))
    assert any(e.code == "DATE_RANGE" for e in errs)


def test_period_validated_once_at_top() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor), _form(payee, _payor(tin="111-222-333-000"))]
    errs = validate(_payee_result(payee=payee, period_from="", period_to="03/31/2026",
                                  forms=forms))
    from_errs = [e for e in errs if e.column == "from_date" and e.code == "REQUIRED"]
    assert len(from_errs) == 1  # not once per form
    assert from_errs[0].row == 3


def test_varying_entity_tin_flagged_per_row() -> None:
    payee = _payee()
    forms = [_form(payee, _payor(tin="bad", name="P1"), excel_row=7)]
    errs = validate(_payee_result(payee=payee, forms=forms))
    assert any(e.code == "TIN_FORMAT" and e.column == "payor_tin" and e.row == 7
               for e in errs)


def test_unknown_atc_flagged() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor, ewt=[LineItem(description="X", atc="ZZZZZZ",
                                               m1=0, m2=0, m3=0, total=0, tax_withheld=0)])]
    errs = validate(_payee_result(payee=payee, forms=forms))
    assert any(e.code == "ATC_UNKNOWN" and e.column == "atc" for e in errs)


def test_total_mismatch_flagged() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor, ewt=[LineItem(description="X", atc="WI010",
                                              m1=100, m2=100, m3=100,
                                              total=999, tax_withheld=30)])]
    errs = validate(_payee_result(payee=payee, forms=forms))
    assert any(e.code == "TOTAL_MISMATCH" and e.column == "total" for e in errs)


def test_no_line_items_flagged() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor, ewt=[], money_payments=[])]
    errs = validate(_payee_result(payee=payee, forms=forms))
    assert any(e.code == "NO_LINE_ITEMS" for e in errs)


def test_negative_amount_flagged() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor, ewt=[LineItem(description="X", atc="WI010",
                                              m1=-1, m2=0, m3=0, total=-1, tax_withheld=0)])]
    errs = validate(_payee_result(payee=payee, forms=forms))
    assert any(e.code == "AMOUNT_NEGATIVE" for e in errs)


def test_partial_line_item_flagged() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor, ewt=[LineItem(description="X", atc="",
                                              m1=0, m2=0, m3=0, total=0, tax_withheld=10)])]
    errs = validate(_payee_result(payee=payee, forms=forms))
    assert any(e.code == "LINE_ITEM_PARTIAL" and e.column == "description" for e in errs)


def test_line_item_error_uses_line_item_excel_row() -> None:
    payee, payor = _payee(), _payor()
    forms = [_form(payee, payor, excel_row=7,
                   ewt=[LineItem(description="X", atc="ZZZZZZ", excel_row=9,
                                 m1=0, m2=0, m3=0, total=0, tax_withheld=0)])]
    errs = validate(_payee_result(payee=payee, forms=forms))
    atc_errs = [e for e in errs if e.code == "ATC_UNKNOWN"]
    assert atc_errs and atc_errs[0].row == 9
