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


def test_extract_jobs_have_their_own_slots_and_runs_page_by_fifty():
    import inspect

    from app.routers import accounting_extract
    from app.services.accounting import pipeline
    from app.services.accounting.extract import runner

    assert runner._SLOTS is not pipeline._SLOTS and runner._SLOTS._total._value == 2
    params = inspect.signature(accounting_extract.list_runs).parameters
    assert params["offset"].default.default == 0 and params["limit"].default.default == runner.RUNS_LISTED == 50
    assert AAExtractRecord.__table__.c.bad_cells.default.arg.__name__ == "list"
