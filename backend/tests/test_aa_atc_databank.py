from datetime import date

from app.routers.accounting_atc import ATC_ACCOUNTS
from app.routers.accounting_periods import document_atc_source, doc_line
from app.services.accounting.atc_prefs import SeenSupplier, account_key, remembered_atc, supplier_rows
from app.services.accounting.rls import rls_statements
from tests.test_aa_wiring import _doc

PREFS = {"111222333": "WC120", account_key("rent"): "WC100", account_key("repairs"): "NONE"}


def test_supplier_wins_over_account_default_which_wins_over_nothing():
    assert remembered_atc(PREFS, "111222333", "rent") == ("WC120", "supplier")
    assert remembered_atc(PREFS, "999888777", "rent") == ("WC100", "account")
    assert remembered_atc(PREFS, "", "rent") == ("WC100", "account")
    assert remembered_atc(PREFS, "999888777", "utilities") == ("", "")


def test_doc_line_uses_the_databank_after_the_documents_own_atc():
    assert doc_line(_doc(seller_tin="999888777"), PREFS).ewt_atc == "WC100"
    assert doc_line(_doc(seller_tin="999888777", account="repairs"), PREFS).ewt_atc == "NONE"
    assert doc_line(_doc(ewt_atc="WI100"), PREFS).ewt_atc == "WI100"
    assert doc_line(_doc(client_role="seller", category="sales"), PREFS).ewt_atc == ""


def test_document_atc_source():
    assert document_atc_source(_doc(ewt_atc="WI100"), PREFS) == "document"
    assert document_atc_source(_doc(), PREFS) == "supplier"
    assert document_atc_source(_doc(seller_tin="999888777"), PREFS) == "account"
    assert document_atc_source(_doc(seller_tin="999888777", account="utilities"), PREFS) == ""


def test_supplier_rows_merge_seen_suppliers_rules_and_suggestions():
    seen = [SeenSupplier("111222333", "Ayala Land Inc.", 4, date(2026, 7, 1)),
            SeenSupplier("444555666", "Bob Repairs", 2, None)]
    rules = {"111222333": ("WC100", "Ayala"), "777888999": ("WI010", "Atty. Cruz"), "000111222": ("", "Old")}
    elsewhere = {"444555666": ("WI120", "Other Co"), "111222333": ("WC120", "Other Co")}
    rows = supplier_rows(seen, rules, elsewhere)
    assert [(r.tin, r.name, r.documents, r.ewt_atc, r.suggestion, r.suggestion_company) for r in rows] == [
        ("777888999", "Atty. Cruz", 0, "WI010", "", ""),
        ("111222333", "Ayala Land Inc.", 4, "WC100", "", ""),   # its own ATC: no suggestion
        ("444555666", "Bob Repairs", 2, "", "WI120", "Other Co"),
    ]


def test_salaries_take_no_expanded_withholding_default():
    assert "salaries" not in ATC_ACCOUNTS and "rent" in ATC_ACCOUNTS


def test_atc_defaults_are_firm_scoped_through_their_company():
    joined = "\n".join(rls_statements())
    assert "CREATE POLICY aa_atc_defaults_firm ON aa_atc_defaults" in joined
    assert "c.id = aa_atc_defaults.company_id" in joined and "c.id = aa_supplier_rules.company_id" in joined
