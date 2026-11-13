from app.models.accounting import AAExtractDraft, AAExtractFile, AAExtractFormat, AAExtractRecord, AAExtractRun
from app.services import access, features
from app.services.accounting import audit
from app.services.accounting.rls import rls_statements

TABLES = ("aa_extract_formats", "aa_extract_drafts", "aa_extract_runs", "aa_extract_files", "aa_extract_records")


def test_tables_exist_with_firm_scope():
    for model, table in zip((AAExtractFormat, AAExtractDraft, AAExtractRun, AAExtractFile, AAExtractRecord), TABLES):
        assert model.__tablename__ == table and "enterprise_id" in model.__table__.c


def test_rls_covers_every_table_and_admin_reads_formats_only():
    sql = "\n".join(rls_statements())
    for table in TABLES:
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
    admin = [s for s in rls_statements() if "aa_extract_formats_admin_read" in s and s.startswith("CREATE")]
    assert len(admin) == 1 and "FOR SELECT" in admin[0] and "u.role = 'admin'" in admin[0]
    assert "aa_extract_records_admin" not in sql and "aa_extract_runs_admin" not in sql


def test_switch_and_audit_plumbing():
    assert "extract" in features.KEYS and "extract" in access.PERSONAL_KEYS
    assert {"extract_format", "extract_run"} <= audit.ENTITIES
