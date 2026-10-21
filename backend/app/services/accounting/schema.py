"""Additive column migrations for existing aa_* tables (idempotent; run at startup after create_all).

New databases get these columns from the models via create_all; existing ones get them here.
"""


def column_statements() -> list[str]:
    return [
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS owner_name VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS review_overrides JSONB NOT NULL DEFAULT '{}'::jsonb",
        # create_all also creates this table; keep the additive setup explicit for existing installations.
        "CREATE TABLE IF NOT EXISTS aa_audit_events ("
        "id UUID PRIMARY KEY, enterprise_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "company_id UUID REFERENCES aa_companies(id) ON DELETE SET NULL, "
        "user_id UUID REFERENCES users(id) ON DELETE SET NULL, user_name VARCHAR(255) NOT NULL DEFAULT '', "
        "at TIMESTAMPTZ NOT NULL DEFAULT now(), entity VARCHAR(40) NOT NULL, entity_id VARCHAR(100) NOT NULL, "
        "action VARCHAR(40) NOT NULL, before JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "after JSONB NOT NULL DEFAULT '{}'::jsonb, reason TEXT NOT NULL DEFAULT '')",
        "CREATE INDEX IF NOT EXISTS ix_aa_audit_events_scope_at ON aa_audit_events (enterprise_id, company_id, at)",
        "CREATE INDEX IF NOT EXISTS ix_aa_audit_events_entity ON aa_audit_events (enterprise_id, entity, entity_id)",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS ewt_atc VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS ewt_atc VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS operations_start_year INTEGER",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS facts_updated_at TIMESTAMPTZ",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS filed_output_id UUID "
        "REFERENCES aa_outputs(id) ON DELETE SET NULL",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS contact_number VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS email VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS taxpayer_classification VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS filed_forms JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_kept JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_start DATE",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_signatory VARCHAR(120) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_signatory_title VARCHAR(60) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_updated_at TIMESTAMPTZ",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS paid_on DATE",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS paid_via VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS payment_ref VARCHAR(60) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS settles_document_id UUID "
        "REFERENCES aa_documents(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_settles_document_id ON aa_documents (settles_document_id)",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS settles_source VARCHAR(5) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS gl_account_code VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS gl_account_code VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS counterparty_name VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS not_duplicate_of JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_assets ALTER COLUMN document_id DROP NOT NULL",  # opening assets have no document
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS has_compensation_income BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS payroll_mapping JSONB NOT NULL DEFAULT '{}'::jsonb",
    ]
