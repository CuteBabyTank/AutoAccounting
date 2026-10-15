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
