from app.models.accounting import AAAccount, AACompany, AADocument, AAJournalEntry, AASupplierRule
from app.services.accounting.schema import column_statements


def test_new_columns_exist_on_models():
    assert {"books_kept", "books_start", "books_signatory", "books_signatory_title", "books_updated_at"} <= set(
        AACompany.__table__.columns.keys())
    assert {"paid_on", "paid_via", "payment_ref", "settles_document_id", "settles_source", "gl_account_code"} <= set(
        AADocument.__table__.columns.keys())
    assert "gl_account_code" in AASupplierRule.__table__.columns.keys()
    assert {"code", "name", "type", "contra", "parent_code", "system_key", "active"} <= set(
        AAAccount.__table__.columns.keys())
    assert {"kind", "book", "entry_date", "reference", "particulars", "lines", "deleted_at"} <= set(
        AAJournalEntry.__table__.columns.keys())


def test_existing_databases_get_every_new_column():
    sql = "\n".join(column_statements())
    for table, column in (
        ("aa_companies", "books_kept"), ("aa_companies", "books_start"), ("aa_companies", "books_signatory"),
        ("aa_companies", "books_signatory_title"), ("aa_companies", "books_updated_at"),
        ("aa_documents", "paid_on"), ("aa_documents", "paid_via"), ("aa_documents", "payment_ref"),
        ("aa_documents", "settles_document_id"), ("aa_documents", "settles_source"),
        ("aa_documents", "gl_account_code"), ("aa_supplier_rules", "gl_account_code"),
    ):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} " in sql, (table, column)
    assert "CREATE INDEX IF NOT EXISTS ix_aa_documents_settles_document_id" in sql


def test_bank_columns_exist_on_models_and_existing_databases():
    assert "bank_account_no" in AAAccount.__table__.columns.keys()
    assert "review_flags" in AACompany.__table__.columns.keys()
    sql = "\n".join(column_statements())
    assert "ALTER TABLE aa_accounts ADD COLUMN IF NOT EXISTS bank_account_no " in sql
    assert "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS review_flags " in sql


def test_adjusting_flag_on_journal_entries():
    import pytest
    from pydantic import ValidationError

    from app.schemas.accounting_books import JournalEntryIn

    assert "is_adjusting" in AAJournalEntry.__table__.columns.keys()
    assert ("ALTER TABLE aa_journal_entries ADD COLUMN IF NOT EXISTS is_adjusting BOOLEAN NOT NULL DEFAULT false"
            in column_statements())
    lines = [{"account_code": "6020", "debit": "300"}, {"account_code": "2010", "credit": "300"}]
    assert JournalEntryIn(entry_date="2026-12-15", lines=lines).is_adjusting is False
    assert JournalEntryIn(entry_date="2026-12-15", lines=lines, is_adjusting=True).is_adjusting is True
    with pytest.raises(ValidationError):
        JournalEntryIn(kind="opening", entry_date="2026-01-01", lines=lines, is_adjusting=True)
