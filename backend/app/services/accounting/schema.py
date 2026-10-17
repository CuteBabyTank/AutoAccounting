"""Additive column migrations for existing aa_* tables (idempotent; run at startup after create_all).

New databases get these columns from the models via create_all; existing ones get them here.
"""


def column_statements() -> list[str]:
    return [
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
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS review_notes JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS owner_names JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_audit_events ADD COLUMN IF NOT EXISTS label VARCHAR(200) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_accounts ADD COLUMN IF NOT EXISTS bank_account_no VARCHAR(40) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS review_flags JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS cwt_2307 JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_audit_events ALTER COLUMN company_id DROP NOT NULL",  # firm-level events (settings, tasks)
        "ALTER TABLE aa_journal_entries ADD COLUMN IF NOT EXISTS is_adjusting BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS pack_notes TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS pack_files JSONB NOT NULL DEFAULT '{}'::jsonb",
    ]
