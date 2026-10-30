"""Row-level security for the aa_* tables (defence in depth behind the router's scoping).

Every row belongs to a firm (the enterprise owner's user id). The policy admits
rows of the firm of the user bound via ``app.current_user_id`` (set per request
and per background job by ``bind_session_user``). Unbound sessions see nothing.

Applied from ``startup_migrations`` after ``create_all`` rather than alembic:
``start.sh`` runs alembic before the app creates these tables.
"""

_FIRM_EXPR = (
    "(SELECT CASE WHEN u.role IN ('admin', 'enterprise') THEN u.id ELSE u.enterprise_id END "
    "FROM users u WHERE u.id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)"
)

_FIRM_TABLES = ("aa_companies", "aa_uploads", "aa_files", "aa_documents", "aa_periods", "aa_outputs", "aa_assets",
                "aa_accounts", "aa_journal_entries", "aa_book_closes", "aa_employees", "aa_bank_statements",
                "aa_bank_lines", "aa_bank_rules", "aa_bank_reconciliations", "aa_contacts", "aa_work_items",
                "aa_tasks", "aa_firm_settings", "aa_notification_states", "aa_coa_templates",
                "aa_opening_items", "aa_recurring_entries", "aa_checklist_templates", "aa_import_batches",
                "aa_assistant_usage")
_COMPANY_TABLES = ("aa_supplier_rules", "aa_atc_defaults")  # no enterprise_id: scoped through their company
_APPEND_ONLY_TABLES = ("aa_audit_events",)  # read and insert only: nobody rewrites history


def _company_scope(table: str) -> str:
    return f"EXISTS (SELECT 1 FROM aa_companies c WHERE c.id = {table}.company_id AND c.enterprise_id = {_FIRM_EXPR})"


def _policy(table: str, condition: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {table}_firm ON {table}",
        f"CREATE POLICY {table}_firm ON {table} FOR ALL USING ({condition}) WITH CHECK ({condition})",
    ]


def _append_only_policy(table: str, condition: str) -> list[str]:
    """SELECT and INSERT policies only: under FORCE RLS, UPDATE and DELETE match no rows."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {table}_firm ON {table}",
        f"DROP POLICY IF EXISTS {table}_insert ON {table}",
        f"CREATE POLICY {table}_firm ON {table} FOR SELECT USING ({condition})",
        f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({condition})",
    ]


def rls_statements() -> list[str]:
    statements: list[str] = []
    for table in _FIRM_TABLES:
        statements += _policy(table, f"enterprise_id = {_FIRM_EXPR}")
    for table in _COMPANY_TABLES:
        statements += _policy(table, _company_scope(table))
    for table in _APPEND_ONLY_TABLES:
        statements += _append_only_policy(table, f"enterprise_id = {_FIRM_EXPR}")
    # Platform reporting needs cross-firm reads, never cross-firm writes.
    statements += [
        "DROP POLICY IF EXISTS aa_assistant_usage_admin_read ON aa_assistant_usage",
        "CREATE POLICY aa_assistant_usage_admin_read ON aa_assistant_usage FOR SELECT USING ("
        "EXISTS (SELECT 1 FROM users u WHERE u.role = 'admin' AND u.id = "
        "NULLIF(current_setting('app.current_user_id', true), '')::uuid))",
    ]
    return statements
