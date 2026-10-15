from app.services.accounting.books.chart import (
    Chart, ChartAccount, default_books, missing_standard, standard_chart,
)
from app.services.accounting.extraction import EXPENSE_ACCOUNTS


def test_codes_and_system_keys_are_unique():
    chart = standard_chart("corporation")
    codes = [a.code for a in chart]
    keys = [a.system_key for a in chart if a.system_key]
    assert len(codes) == len(set(codes)) and len(keys) == len(set(keys))


def test_every_document_account_maps_to_a_chart_account():
    chart = Chart(standard_chart("corporation"))
    for account in EXPENSE_ACCOUNTS:
        assert chart.get(chart.doc_account(account)) is not None, account
    assert chart.doc_account("capital_goods") == chart.code("ppe")
    assert chart.doc_account("no_such_account") == chart.code("doc:other")


def test_equity_account_name_follows_taxpayer_type():
    names = {t: Chart(standard_chart(t)).name(Chart(standard_chart(t)).code("capital"))
             for t in ("corporation", "individual", "partnership")}
    assert names == {"corporation": "Share capital", "individual": "Owner's capital",
                     "partnership": "Partners' capital"}


def test_normal_balances():
    chart = Chart(standard_chart("corporation"))
    assert chart.get(chart.code("cash")).debit_normal
    assert not chart.get(chart.code("accum_dep")).debit_normal      # contra asset
    assert not chart.get(chart.code("sales")).debit_normal
    assert chart.get(chart.code("sales_returns")).debit_normal      # contra income
    assert chart.get(chart.code("drawings")).debit_normal           # contra equity


def test_override_used_only_when_active():
    accounts = standard_chart("corporation") + [
        ChartAccount("6021", "Rent - warehouse", "expense", parent_code="6020"),
        ChartAccount("6022", "Rent - old", "expense", parent_code="6020", active=False),
    ]
    chart = Chart(accounts)
    assert chart.doc_account("rent", "6021") == "6021"
    assert chart.doc_account("rent", "6022") == chart.code("doc:rent")
    assert chart.doc_account("rent", "9999") == chart.code("doc:rent")


def test_missing_standard_accounts():
    full = standard_chart("corporation")
    older = [a for a in full if a.system_key != "input_vat_expense"]
    missing = missing_standard(older, "corporation")
    assert [a.system_key for a in missing] == ["input_vat_expense"]
    assert missing_standard(full, "corporation") == []


def test_unknown_system_key_raises():
    import pytest
    with pytest.raises(KeyError):
        Chart([]).code("cash")


def test_default_books():
    assert default_books(True) == ["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"]
    assert default_books(False) == ["CRJ", "CDJ", "GJ", "GL"]
