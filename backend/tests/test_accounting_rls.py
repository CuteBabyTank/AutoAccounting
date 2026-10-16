from app.models.accounting import (
    AAAccount, AAAsset, AAAtcDefault, AAAuditEvent, AABankLine, AABankReconciliation, AABankRule, AABankStatement, AABookClose, AACompany, AAEmployee, AADocument, AAFile, AAJournalEntry, AAOutput, AAPeriod, AASupplierRule, AAUpload,
)
from app.services.accounting.rls import rls_statements

TABLES = [m.__tablename__ for m in (AACompany, AAUpload, AAFile, AADocument, AASupplierRule, AAPeriod, AAOutput,
                                           AAAsset, AAAccount, AAJournalEntry, AAAtcDefault, AABookClose, AAEmployee,
                                           AABankStatement, AABankLine, AABankRule, AABankReconciliation)]


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
    assert sql.count("WITH CHECK") == len(TABLES) + 1  # + the audit log's insert-only policy


def test_audit_events_are_append_only_for_the_firm():
    sql = "\n".join(rls_statements())
    assert "ALTER TABLE aa_audit_events FORCE ROW LEVEL SECURITY" in sql
    audit = [s for s in rls_statements() if "POLICY" in s and "ON aa_audit_events" in s and "CREATE" in s]
    assert len(audit) == 2
    assert any("FOR SELECT USING" in s for s in audit) and any("FOR INSERT WITH CHECK" in s for s in audit)
    assert not any("FOR ALL" in s or "FOR UPDATE" in s or "FOR DELETE" in s for s in audit)
    assert all(f"enterprise_id = " in s for s in audit)
    assert AAAuditEvent.__tablename__ == "aa_audit_events"
