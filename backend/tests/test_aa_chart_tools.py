"""Chart tools: where an account lands on the statements, chart templates, the locked-account message (pure)."""

import pytest

from app.services.accounting.books.chart import Chart, ChartAccount, locked_message, standard_chart
from app.services.accounting.books.templates import (
    BUILTIN_TEMPLATES, placement, template_accounts, template_rows,
)


def test_placement():
    c = Chart(standard_chart("corporation") + [ChartAccount("4011", "Service revenue", "income", parent_code="4010"),
                                               ChartAccount("2201", "Loan - BDO", "liability", parent_code="2200")])
    assert placement(c, "4011") == "Profit and loss · Revenue"
    assert placement(c, "4020") == "Profit and loss · Revenue (reduces net sales)"
    assert placement(c, "4100") == "Profit and loss · Other income"
    assert placement(c, "5010") == "Profit and loss · Cost of sales"
    assert placement(c, "6020") == "Profit and loss · Operating expenses"
    assert placement(c, "7010") == "Profit and loss · Income tax expense"
    assert placement(c, "1010") == "Balance sheet · Assets"
    assert placement(c, "1510") == "Balance sheet · Assets (reduces the total)"
    assert placement(c, "2201") == "Balance sheet · Liabilities"
    assert placement(c, "3030") == "Balance sheet · Equity (reduces the total)"
    assert placement(c, "9999") == ""


def test_builtin_templates_extend_standard():
    assert set(BUILTIN_TEMPLATES) == {"trading", "services", "manufacturing", "non_vat"}
    standard = {a.code for a in standard_chart("corporation")}
    for key in BUILTIN_TEMPLATES:
        accounts = template_accounts(key, "corporation")
        codes = [a.code for a in accounts]
        assert len(codes) == len(set(codes)) and standard <= set(codes), key
        chart = Chart(accounts)
        for a in accounts:
            if a.code not in standard:
                parent = chart.get(a.parent_code)
                assert parent is not None and (a.type, a.contra) == (parent.type, parent.contra), (key, a.code)
    manufacturing = {a.name for a in template_accounts("manufacturing", "corporation")}
    assert {"Direct labor", "Factory overhead"} <= manufacturing


def test_template_validation():
    rows = template_rows(standard_chart("corporation"))
    with pytest.raises(ValueError, match="twice"):
        template_accounts(rows + [rows[0]], "corporation")
    with pytest.raises(ValueError, match="parent"):
        template_accounts(rows + [{"code": "6999", "name": "X", "type": "expense", "parent_code": "6998"}],
                          "corporation")
    with pytest.raises(ValueError, match="type"):
        template_accounts(rows + [{"code": "6999", "name": "X", "type": "spending"}], "corporation")
    with pytest.raises(ValueError, match="code"):
        template_accounts(rows + [{"code": "69", "name": "X", "type": "expense"}], "corporation")
    with pytest.raises(ValueError, match="Unknown template"):
        template_accounts("bakery", "corporation")


def test_template_round_trip_fills_missing_system_accounts():
    accounts = standard_chart("corporation")
    renamed = [ChartAccount(a.code, "Cash in bank - BDO", a.type, a.contra, a.system_key) if a.system_key == "bank"
               else a for a in accounts if a.system_key != "vat_difference"]
    out = {a.code: a for a in template_accounts(template_rows(renamed), "corporation")}
    assert out["1020"].name == "Cash in bank - BDO"
    assert out["1310"].system_key == "vat_difference"  # filled from the standard chart


def test_template_capital_name_follows_taxpayer():
    rows = template_rows(standard_chart("corporation"))
    out = {a.system_key: a.name for a in template_accounts(rows, "individual")}
    assert out["capital"] == "Owner's capital"
    custom = [dict(r, name="Capital stock") if r["system_key"] == "capital" else r for r in rows]
    assert {a.system_key: a.name for a in template_accounts(custom, "individual")}["capital"] == "Capital stock"


def test_template_rows_drop_locks_and_keep_active():
    rows = template_rows([ChartAccount("6061", "Gifts", "expense", parent_code="6060", active=False, locked=True)])
    assert rows == [{"code": "6061", "name": "Gifts", "type": "expense", "contra": False, "system_key": None,
                     "parent_code": "6060", "active": False}]


def test_locked_message():
    c = Chart(standard_chart("corporation") + [ChartAccount("6061", "Gifts", "expense", parent_code="6060",
                                                            locked=True)])
    assert locked_message(c, ["6020", "6061"]) == ("Account 6061 Gifts is locked: choose another account (unlock it "
                                                   "in the chart of accounts first if this posting is right).")
    assert locked_message(c, ["6020"]) == ""
