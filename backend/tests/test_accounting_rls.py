from app.models.accounting import (
    AAAuditEvent, AAAccount, AAAsset, AAAtcDefault, AABookClose, AACompany, AAEmployee, AADocument, AAFile, AAJournalEntry, AAOutput, AAPeriod, AASupplierRule, AAUpload,
)
from app.services.accounting.rls import rls_statements

TABLES = [m.__tablename__ for m in (AACompany, AAUpload, AAFile, AADocument, AASupplierRule, AAPeriod, AAOutput,
                                           AAAsset, AAAccount, AAJournalEntry, AAAtcDefault, AABookClose, AAEmployee, AAAuditEvent)]


def test_every_accounting_table_is_forced_under_rls_with_one_policy():
    sql = "\n".join(rls_statements())
    for table in TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
        assert f"DROP POLICY IF EXISTS {table}_firm ON {table}" in sql
        assert f"CREATE POLICY {table}_firm ON {table}" in sql


def test_policies_scope_by_the_bound_users_firm():
    sql = "\n".join(rls_statements())
    assert "current_setting('app.current_user_id', true)" in sql
    assert sql.count("WITH CHECK") == len(TABLES)
